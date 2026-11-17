// ssd_bench.c: O_DIRECT read benchmark with io_uring (stand-in for fio, which is not installed).
//
// Usage: ssd_bench <file> <seq|rand> <block_bytes> <queue_depth> <seconds> [span_bytes]
// Prints one JSON line: iops, GB/s, latency percentiles in microseconds.
//
// Method:
//   - open(O_RDONLY | O_DIRECT): the page cache is bypassed, every read goes to the device.
//   - one io_uring with `qd` slots; each slot owns a 4096-aligned buffer.
//   - keep exactly `qd` reads in flight: on each completion, resubmit that slot.
//   - seq: next offset = previous + bs (wraps at span). rand: uniform offset, aligned to bs.
//   - latency per I/O = completion time - submit time (CLOCK_MONOTONIC).
//   IOPS = completed_ops / elapsed_s ; GB/s = completed_ops * bs / elapsed_s / 1e9
//
// Build: gcc -O2 -o ssd_bench ssd_bench.c -luring
#define _GNU_SOURCE
#include <fcntl.h>
#include <liburing.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

static inline double now_s(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

static uint64_t rng_state = 0x9E3779B97F4A7C15ULL;
static inline uint64_t xorshift64(void) {
    uint64_t x = rng_state;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    return rng_state = x;
}

static int cmp_f(const void *a, const void *b) {
    float x = *(const float *)a, y = *(const float *)b;
    return (x > y) - (x < y);
}

int main(int argc, char **argv) {
    if (argc < 6) {
        fprintf(stderr, "usage: %s file seq|rand bs qd seconds [span]\n", argv[0]);
        return 2;
    }
    const char *path = argv[1];
    int is_rand = strcmp(argv[2], "rand") == 0;
    uint64_t bs = strtoull(argv[3], 0, 10);
    unsigned qd = (unsigned)atoi(argv[4]);
    double dur = atof(argv[5]);

    int fd = open(path, O_RDONLY | O_DIRECT);
    if (fd < 0) { perror("open"); return 1; }
    struct stat st;
    fstat(fd, &st);
    uint64_t span = argc > 6 ? strtoull(argv[6], 0, 10) : (uint64_t)st.st_size;
    uint64_t nblocks = span / bs;
    if (nblocks == 0) { fprintf(stderr, "span < bs\n"); return 1; }
    rng_state ^= (uint64_t)time(NULL) * 0x2545F4914F6CDD1DULL;

    struct io_uring ring;
    if (io_uring_queue_init(qd < 8 ? 8 : qd, &ring, 0) < 0) { perror("io_uring_queue_init"); return 1; }

    void **buf = calloc(qd, sizeof(void *));
    double *t_sub = calloc(qd, sizeof(double));
    for (unsigned i = 0; i < qd; i++)
        if (posix_memalign(&buf[i], 4096, bs)) { fprintf(stderr, "alloc\n"); return 1; }

    const size_t LAT_CAP = 4u << 20;  // store up to 4M latency samples (16 MB)
    float *lat = malloc(LAT_CAP * sizeof(float));
    size_t nlat = 0;

    uint64_t seq_next = 0, ops = 0;
    double t0 = now_s(), t_end = t0 + dur;

    // prime the queue: qd reads in flight
    for (unsigned i = 0; i < qd; i++) {
        uint64_t blk = is_rand ? xorshift64() % nblocks : (seq_next++ % nblocks);
        struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
        io_uring_prep_read(sqe, fd, buf[i], bs, blk * bs);
        io_uring_sqe_set_data64(sqe, i);
        t_sub[i] = now_s();
    }
    io_uring_submit(&ring);

    int stopping = 0;
    unsigned inflight = qd;
    while (inflight > 0) {
        struct io_uring_cqe *cqe;
        int r = io_uring_wait_cqe(&ring, &cqe);
        if (r < 0) { fprintf(stderr, "wait_cqe %d\n", r); return 1; }
        unsigned i = (unsigned)io_uring_cqe_get_data64(cqe);
        if (cqe->res != (int)bs) { fprintf(stderr, "short read res=%d\n", cqe->res); return 1; }
        io_uring_cqe_seen(&ring, cqe);
        double t = now_s();
        inflight--;
        if (!stopping) {
            ops++;
            if (nlat < LAT_CAP) lat[nlat++] = (float)((t - t_sub[i]) * 1e6);
            if (t >= t_end) stopping = 1;
        }
        if (!stopping) {
            uint64_t blk = is_rand ? xorshift64() % nblocks : (seq_next++ % nblocks);
            struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
            io_uring_prep_read(sqe, fd, buf[i], bs, blk * bs);
            io_uring_sqe_set_data64(sqe, i);
            t_sub[i] = now_s();
            io_uring_submit(&ring);
            inflight++;
        }
    }
    double el = now_s() - t0;
    qsort(lat, nlat, sizeof(float), cmp_f);
    double sum = 0;
    for (size_t k = 0; k < nlat; k++) sum += lat[k];
#define PCT(p) (nlat ? lat[(size_t)((p) * (nlat - 1))] : 0.0)
    printf("{\"mode\":\"%s\",\"bs\":%llu,\"qd\":%u,\"seconds\":%.3f,\"ops\":%llu,"
           "\"iops\":%.1f,\"GBps\":%.4f,\"lat_mean_us\":%.2f,\"lat_p50_us\":%.2f,"
           "\"lat_p99_us\":%.2f,\"lat_p999_us\":%.2f,\"span\":%llu}\n",
           is_rand ? "rand" : "seq", (unsigned long long)bs, qd, el, (unsigned long long)ops,
           ops / el, ops * (double)bs / el / 1e9, nlat ? sum / nlat : 0.0, PCT(0.50), PCT(0.99),
           PCT(0.999), (unsigned long long)span);
    io_uring_queue_exit(&ring);
    close(fd);
    return 0;
}
