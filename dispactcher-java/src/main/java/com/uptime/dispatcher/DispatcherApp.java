package com.uptime.dispatcher;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;

import javax.sql.DataSource;
import java.net.http.HttpClient;

/**
 * Assembles the object graph and starts the schedule. Does no work itself.
 *
 * This is the only class that knows the database is Postgres at a particular
 * URL, or that the probe pool has twenty threads. Everything downstream
 * receives what it needs and knows nothing about how it was built - which is
 * what lets a test hand Dispatcher a fake repository instead of a real one.
 */
public final class DispatcherApp {

    public static void main(String[] args) {
        Config config = Config.fromEnv();

        DataSource dataSource = buildDataSource(config);

        EndpointRepository repository =
                new EndpointRepository(dataSource, config.claimBatchSize);

        HttpClient httpClient = HttpClient.newBuilder()
                .connectTimeout(config.httpTimeout)
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();

        // TODO(you): construct the probe pool.
        // TODO(you): construct the Dispatcher.
        // TODO(you): construct the scheduler and start the schedule.
        // TODO(you): register the shutdown hook.
    }

    /**
     * Pool sizing note: Hikari's maximumPoolSize must be large enough that a
     * probe thread wanting to write a result is not queued behind other probe
     * threads. Sized against the probe pool, not guessed.
     */
    private static DataSource buildDataSource(Config config) {
        HikariConfig hikari = new HikariConfig();
        hikari.setJdbcUrl(config.jdbcUrl);
        hikari.setUsername(config.dbUser);
        if (!config.dbPassword.isBlank()) {
            hikari.setPassword(config.dbPassword);
        }
        hikari.setMaximumPoolSize(config.probePoolSize / 2 + 2);
        hikari.setPoolName("dispatcher-db");
        return new HikariDataSource(hikari);
    }

    private DispatcherApp() {
    }
}