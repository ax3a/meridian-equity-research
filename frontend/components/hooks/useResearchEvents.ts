"use client";

import { useEffect, useState } from "react";
import { eventsUrl } from "@/lib/api";
import type { ProgressEvent } from "@/lib/types";

export type StreamStatus = "connecting" | "open" | "reconnecting" | "closed";

interface UseResearchEventsResult {
  events: ProgressEvent[];
  streamStatus: StreamStatus;
  lastEvent: ProgressEvent | null;
}

/**
 * Subscribes to the SSE progress stream for a research run through the server-side proxy
 * (`/api/proxy/research/{id}/events`, which forwards to `GET /research/{id}/events` unbuffered).
 *
 * Reconnection is handled by the browser's native `EventSource`: on a dropped connection it retries
 * automatically and sends the `Last-Event-ID` header set to the last `id:` field the server sent (the
 * event's `seq`), which the proxy passes straight through so the backend can resume the stream exactly
 * where it left off. No manual retry/backoff logic is needed here.
 */
export function useResearchEvents(sessionId: string | null): UseResearchEventsResult {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    if (!sessionId) return;
    setEvents([]);
    setStreamStatus("connecting");

    const source = new EventSource(eventsUrl(sessionId));

    const handleMessage = (message: MessageEvent<string>) => {
      try {
        const parsed = JSON.parse(message.data) as ProgressEvent;
        setEvents((prev) => [...prev, parsed]);
      } catch {
        // Malformed frame: drop it rather than crashing the live view.
      }
    };

    source.onopen = () => setStreamStatus("open");
    source.onerror = () => {
      setStreamStatus(source.readyState === EventSource.CLOSED ? "closed" : "reconnecting");
    };
    source.onmessage = handleMessage;
    // Defensive: also handle a named "progress" event in case the backend emits one instead of the
    // default "message" event type.
    source.addEventListener("progress", handleMessage as EventListener);

    return () => {
      source.close();
    };
  }, [sessionId]);

  return { events, streamStatus, lastEvent: events.length ? events[events.length - 1]! : null };
}
