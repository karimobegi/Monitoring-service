package com.uptime.dispatcher;

public record Endpoint(int id, String url, int intervalSeconds) {
}