package com.uptime.dispatcher;

import java.time.Duration;

/**
 * All tunable values, read once at startup from the environment.
 *
 * Nothing else in the codebase calls System.getenv. If a value is
 * configurable, it appears here and is passed to whoever needs it.
 */
public final class Config {

    public final String jdbcUrl;
    public final String dbUser;
    public final String dbPassword;

    /** How often the dispatcher wakes up and asks the database what is due. */
    public final Duration tickInterval;

    /** Applied to every probe. There is no per-endpoint timeout column in the Week 1 schema. */
    public final Duration httpTimeout;

    public final int probePoolSize;
    public final int probeQueueCapacity;

    /** Upper bound on rows returned by a single claim. */
    public final int claimBatchSize;

    private Config(
            String jdbcUrl,
            String dbUser,
            String dbPassword,
            Duration tickInterval,
            Duration httpTimeout,
            int probePoolSize,
            int probeQueueCapacity,
            int claimBatchSize) {
        this.jdbcUrl = jdbcUrl;
        this.dbUser = dbUser;
        this.dbPassword = dbPassword;
        this.tickInterval = tickInterval;
        this.httpTimeout = httpTimeout;
        this.probePoolSize = probePoolSize;
        this.probeQueueCapacity = probeQueueCapacity;
        this.claimBatchSize = claimBatchSize;
    }

    public static Config fromEnv() {
        return new Config(
                env("DISPATCHER_JDBC_URL", "jdbc:postgresql://localhost:5432/uptime"),
                env("DISPATCHER_DB_USER", "karimobegi"),
                env("DISPATCHER_DB_PASSWORD", ""),
                Duration.ofSeconds(envInt("DISPATCHER_TICK_SECONDS", 10)),
                Duration.ofSeconds(envInt("DISPATCHER_HTTP_TIMEOUT_SECONDS", 5)),
                envInt("DISPATCHER_PROBE_POOL_SIZE", 20),
                envInt("DISPATCHER_PROBE_QUEUE_CAPACITY", 40),
                envInt("DISPATCHER_CLAIM_BATCH_SIZE", 200));
    }

    private static String env(String key, String fallback) {
        String v = System.getenv(key);
        return (v == null || v.isBlank()) ? fallback : v;
    }

    private static int envInt(String key, int fallback) {
        String v = System.getenv(key);
        if (v == null || v.isBlank()) {
            return fallback;
        }
        return Integer.parseInt(v.trim());
    }
}