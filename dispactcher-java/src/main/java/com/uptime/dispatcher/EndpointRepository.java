package com.uptime.dispatcher;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;

/**
 * The only class in this codebase that touches JDBC.
 *
 * Holds a DataSource, never a Connection. Every method borrows a connection,
 * uses it, and returns it via try-with-resources. That is what makes this
 * object safe to share across the dispatcher thread and all twenty probe
 * threads simultaneously.
 */
public class EndpointRepository {

    /**
     * The atomic claim.
     *
     * The inner SELECT picks the due rows; the outer UPDATE marks them taken
     * and returns them in one statement. A second dispatcher running the same
     * statement concurrently cannot claim the same row, because by the time it
     * evaluates its own WHERE the row no longer satisfies next_check_at <= now().
     *
     * FOR UPDATE SKIP LOCKED means a concurrent claimer steps over rows already
     * locked by an in-flight claim rather than blocking behind them.
     *
     * LIMIT bounds the batch. Without it, a database that has been unreachable
     * for an hour returns every overdue endpoint at once on recovery.
     */
    private static final String CLAIM_SQL = """
            UPDATE endpoint
            SET next_check_at = now() + (interval_seconds * interval '1 second')
            WHERE id IN (
                SELECT id FROM endpoint
                WHERE is_active AND next_check_at <= now()
                ORDER BY next_check_at
                LIMIT ?
                FOR UPDATE SKIP LOCKED
            )
            RETURNING id, url, interval_seconds
            """;

    private static final String INSERT_RESULT_SQL = """
            INSERT INTO checkresult
                (endpoint_id, checked_at, status_code, error, response_time_ms)
            VALUES (?, ?, ?, ?, ?)
            """;

    private final DataSource dataSource;
    private final int claimBatchSize;

    public EndpointRepository(DataSource dataSource, int claimBatchSize) {
        this.dataSource = dataSource;
        this.claimBatchSize = claimBatchSize;
    }

    /**
     * Called once per tick, on the dispatcher thread.
     */
    public List<Endpoint> claimDue() throws SQLException {
        List<Endpoint> claimed = new ArrayList<>();
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(CLAIM_SQL)) {

            ps.setInt(1, claimBatchSize);

            try (ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    claimed.add(new Endpoint(
                            rs.getInt("id"),
                            rs.getString("url"),
                            rs.getInt("interval_seconds")));
                }
            }
        }
        return claimed;
    }

    /**
     * Called once per probe, on whichever probe thread ran it.
     *
     * statusCode, error and responseTimeMs are all nullable, and which are set
     * describes the shape of the outcome:
     *   success  -> statusCode set, error null, responseTimeMs set
     *   failure  -> statusCode null, error set, responseTimeMs null
     *
     * checkedAt is passed in rather than taken here, so it reflects when the
     * probe started rather than when the row happened to be written.
     */
    public void insertResult(
            int endpointId,
            OffsetDateTime checkedAt,
            Integer statusCode,
            String error,
            Integer responseTimeMs) throws SQLException {

        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(INSERT_RESULT_SQL)) {

            ps.setInt(1, endpointId);
            ps.setObject(2, checkedAt);

            if (statusCode == null) {
                ps.setNull(3, Types.INTEGER);
            } else {
                ps.setInt(3, statusCode);
            }

            if (error == null) {
                ps.setNull(4, Types.VARCHAR);
            } else {
                ps.setString(4, error);
            }

            if (responseTimeMs == null) {
                ps.setNull(5, Types.INTEGER);
            } else {
                ps.setInt(5, responseTimeMs);
            }

            ps.executeUpdate();
        }
    }
}