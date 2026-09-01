package com.uptime.dispatcher;

import org.junit.jupiter.api.Test;

import com.uptime.dispatcher.Dispatcher;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.net.http.HttpClient;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.stream.IntStream;
import java.time.Duration;

class DispatcherTest {
    static class FakeRepository extends EndpointRepository {
    private final int count;
    FakeRepository(int count) { super(null, 0); this.count = count; }

    @Override
    public List<Endpoint> claimDue() {
        return IntStream.rangeClosed(1, count)
            .mapToObj(i -> new Endpoint(i, "http://host" + i, 60))
            .toList();
    }
}
    @Test
    void tickSubmitsOneTaskPerClaimedEndpoint(){
        FakeRepository repository = new FakeRepository(3);
        ThreadPoolExecutor pool = new ThreadPoolExecutor(
            1, 1, 0L, TimeUnit.MILLISECONDS,
            new ArrayBlockingQueue<>(10));
        Dispatcher dispatcher = new Dispatcher(repository, pool, Duration.ofSeconds(5), HttpClient.newHttpClient());
        dispatcher.run();
        assertEquals(3, pool.getTaskCount());
    }

    @Test
    void rejectionsAreCountedWhenPoolIsSaturated() throws Exception {
    ThreadPoolExecutor pool = new ThreadPoolExecutor(
        1, 1, 0L, TimeUnit.MILLISECONDS,
        new ArrayBlockingQueue<>(1));

    CountDownLatch block = new CountDownLatch(1);

    // Occupies the single thread until we release it.
    pool.submit(() -> {
        try { block.await(); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    });

    pool.submit(() -> { });

    Dispatcher dispatcher = new Dispatcher(
        new FakeRepository(5), pool, Duration.ofSeconds(5), HttpClient.newHttpClient());

    dispatcher.run();

    assertEquals(5, dispatcher.rejectedProbeCount());

    block.countDown();   // let the blocker finish so the JVM can exit
    pool.shutdown();
        }
    }   
