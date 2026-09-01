package com.uptime.dispatcher;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.sql.SQLException;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.net.ConnectException;
import java.net.UnknownHostException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * One endpoint, one HTTP request, one result row. Runs on a probe pool thread;
 * up to poolSize instances are in flight at once.
 *
 * SKELETON - the body is yours to write.
 */
public class ProbeTask implements Runnable {

    private final Endpoint endpoint;
    private final EndpointRepository repository;
    private final HttpClient httpClient;
    private final Duration timeout;
    private static final Logger log = LoggerFactory.getLogger(ProbeTask.class);

    public ProbeTask(
            Endpoint endpoint,
            EndpointRepository repository,
            HttpClient httpClient,
            Duration timeout) {
        this.endpoint = endpoint;
        this.repository = repository;
        this.httpClient = httpClient;
        this.timeout = timeout;
    }

    /**
     * Capture the start time, issue the request, write the result.
     *
     * Points worth deciding rather than defaulting:
     *
     *  - The timeout must go on the HttpRequest. Nothing else bounds how long
     *    this thread is held; ScheduledExecutorService cannot interrupt it and
     *    the pool cannot reclaim it.
     *
     *  - Map exceptions to the error strings the Python side already writes:
     *    timeout, dns_failure, connection_refused. Same vocabulary, or the two
     *    implementations produce rows that cannot be compared.
     *
     *  - A failed HTTP request is a measurement and gets a row. A failure to
     *    write that row is not - decide what happens if insertResult throws.
     *
     *  - Nothing catches what escapes this method. A pool thread dying from an
     *    uncaught exception is replaced silently by the pool.
     */
@Override
public void run() {
    OffsetDateTime startedAt = OffsetDateTime.now();
    long startNanos = System.nanoTime();
    Integer statusCode = null;
    String error = null;
    Integer responseTimeMs = null;

    try {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(endpoint.url()))
                .timeout(timeout)
                .GET()
                .build();

        HttpResponse<Void> response =
                httpClient.send(request, HttpResponse.BodyHandlers.discarding());

        statusCode = response.statusCode();
        responseTimeMs = (int) ((System.nanoTime() - startNanos) / 1_000_000);
    }
    catch (HttpTimeoutException e) { error = "timeout"; }
    catch (ConnectException e) { error = "connection_refused"; }
    catch (UnknownHostException e) { error = "dns_failure"; }
    catch (IOException e) { error = "unknown"; }
    catch (InterruptedException e) {
        Thread.currentThread().interrupt();
        return;
    }
    try {
        repository.insertResult(endpoint.id(), startedAt, statusCode, error, responseTimeMs);
    } catch (SQLException e) {
        log.error("failed to write result for endpoint={}", endpoint.id(), e);
    }
    }
}