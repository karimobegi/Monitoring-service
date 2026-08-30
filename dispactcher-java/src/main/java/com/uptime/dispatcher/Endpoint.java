package com.uptime.dispatcher;

/**
 * One claimed row. Immutable, so it crosses the boundary from the
 * dispatcher thread to a probe thread without any synchronisation.
 *
 * Only the three columns the dispatcher actually uses are carried.
 * user_id and next_check_at exist on the table but no probe needs them.
 */
public record Endpoint(int id, String url, int intervalSeconds) {
}