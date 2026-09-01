package com.uptime.dispatcher;

import java.net.http.HttpClient;
import java.time.Duration;

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
        throw new UnsupportedOperationException("yours to write");
    }
}