// Live match updates pushed by the server over a WebSocket.
//
// A "hook" is a reusable piece of component logic; by convention its name
// starts with "use". Any page that calls useMatchUpdates(callback) gets the
// callback run every time one of the user's matches changes (progress,
// completion, failure), without refreshing the page.
import { useEffect, useRef } from "react";
import { io } from "socket.io-client";
import type { Match } from "./types";

export function useMatchUpdates(onUpdate: (match: Match) => void): void {
  // Keep the latest callback in a ref, so the socket is not reconnected
  // every time the page re-renders with a new callback function.
  const callback = useRef(onUpdate);
  useEffect(() => {
    callback.current = onUpdate;
  });

  useEffect(() => {
    // Same origin as the page; the login cookie authenticates the socket.
    const socket = io({ withCredentials: true });
    socket.on("match:updated", (match: Match) => callback.current(match));
    return () => {
      socket.disconnect(); // clean up when the page is left
    };
  }, []);
}
