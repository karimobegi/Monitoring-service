package com.uptime.dispatcher;

import org.junit.jupiter.api.Test;

import com.uptime.dispatcher.Dispatcher;
import com.uptime.dispatcher.Endpoint;
import com.uptime.dispatcher.EndpointRepository;
import com.uptime.dispatcher.ProbeTask;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import static org.junit.jupiter.api.Assertions.assertTrue;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.http.HttpClient;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.stream.IntStream;
import java.time.Duration;

import java.time.OffsetDateTime;
import static org.junit.jupiter.api.Assertions.assertNull;

class ProbeTaskTest {

    static class CapturingRepository extends EndpointRepository {
        Integer endpointId;
        OffsetDateTime checkedAt;
        Integer statusCode;
        String error;
        Integer responseTimeMs;
        int callCount = 0;

        CapturingRepository() { super(null, 0); }

        @Override
        public void insertResult(int endpointId, OffsetDateTime checkedAt,
                                 Integer statusCode, String error, Integer responseTimeMs) {
            this.endpointId = endpointId;
            this.checkedAt = checkedAt;
            this.statusCode = statusCode;
            this.error = error;
            this.responseTimeMs = responseTimeMs;
            this.callCount++;
        }
    }

    private HttpServer server;
    private int port;

    @BeforeEach
    void startServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.createContext("/slow", exchange -> {
            try { Thread.sleep(10_000); } catch (InterruptedException e) { }
            exchange.sendResponseHeaders(200, -1);
        });
        server.start();
        port = server.getAddress().getPort();
    }

    @AfterEach
    void stopServer() {
        server.stop(0);
    }
    @Test
    void refusedConnectionIsRecordedAsConnectionRefused() {
        CapturingRepository cr = new CapturingRepository();
        Endpoint endpoint = new Endpoint(1, "http://localhost:1", 60);
        ProbeTask probeTask = new ProbeTask(
            endpoint, cr, HttpClient.newHttpClient(), Duration.ofSeconds(5));

        probeTask.run();

        assertEquals(1, cr.callCount);
        assertEquals("connection_refused", cr.error);
        assertNull(cr.statusCode);
        assertNull(cr.responseTimeMs);
    }
    @Test
    void slowEndpointIsRecordedAsTimeout() {
        CapturingRepository cr = new CapturingRepository();
        Endpoint endpoint = new Endpoint(1, "http://localhost:" + port + "/slow", 60);
        ProbeTask probeTask = new ProbeTask(
            endpoint, cr, HttpClient.newHttpClient(), Duration.ofSeconds(1));
        long start = System.nanoTime();
        probeTask.run();
        long elapsedMs = (System.nanoTime() - start) / 1_000_000;
        assertEquals("timeout", cr.error);
        assertNull(cr.statusCode);
        assertNull(cr.responseTimeMs);
        assertTrue(elapsedMs < 3000, "probe should have timed out, took " + elapsedMs + "ms");

    }
}