package com.uptime.dispatcher;

import java.time.Duration;
import java.net.http.HttpClient;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.atomic.AtomicInteger;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.uptime.dispatcher.Endpoint;
import com.uptime.dispatcher.EndpointRepository;
import com.uptime.dispatcher.ProbeTask;

/**
 * The tick body. Runs on the single scheduler thread.
 *
 * SKELETON - the body is yours to write. Signatures and fields only.
 */
public class Dispatcher implements Runnable {

    private final EndpointRepository repository;
    private final ThreadPoolExecutor probePool;
    private final HttpClient httpClient;
    private final Duration timeout;

    private final AtomicInteger rejectedProbes = new AtomicInteger();
    private static final Logger log = LoggerFactory.getLogger(Dispatcher.class);

    public Dispatcher(
            EndpointRepository repository,
            ThreadPoolExecutor probePool,
            Duration timeout,
            HttpClient httpClient) {
        this.repository = repository;
        this.probePool = probePool;
        this.timeout = timeout;
        this.httpClient = httpClient;
    }

    /**
     * One tick: claim, then submit one ProbeTask per claimed endpoint.
     *
     * Two things this method must do that are easy to leave out:
     *
     *  1. Catch everything. An exception escaping a scheduleAtFixedRate task
     *     cancels the periodic task permanently, with no output. The monitor
     *     stops monitoring and nothing says so.
     *
     *  2. Handle rejection. A full pool throws RejectedExecutionException from
     *     submit(), on this thread. That is not an endpoint failure and must
     *     not produce a checkresult row - the endpoint was probably fine, the
     *     monitor was saturated. Count it and log it.
     */
    @Override
    public void run() {
        try{
            List<Endpoint> claim = repository.claimDue();
            for (Endpoint endpoint : claim){
                try{
                    ProbeTask probeTask = new ProbeTask(endpoint, repository, httpClient, timeout);
                    probePool.execute(probeTask);
                }
                catch(RejectedExecutionException r){
                    rejectedProbes.getAndIncrement();
                    log.warn("probe rejected, endpoint={} url={}", endpoint.id(), endpoint.url());
                }
            }
            log.info("tick complete, claimed={} queued={} rejectedTotal={}",
            claim.size(), probePool.getQueue().size(), rejectedProbes.get());
        }
        catch(Exception e){
            log.error("dispatcher tick failed", e);
        }
    }

    public int rejectedProbeCount() {
        return rejectedProbes.get();
    }
}