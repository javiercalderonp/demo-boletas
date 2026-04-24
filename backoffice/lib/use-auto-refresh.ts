"use client";

import { useEffect, useRef } from "react";

import { subscribeToApiMutations } from "@/lib/api-events";

const DEFAULT_INTERVAL_MS = 3000;

type AutoRefreshOptions = {
  enabled?: boolean;
  intervalMs?: number;
};

export function useAutoRefresh(
  refresh: () => void | Promise<void>,
  { enabled = true, intervalMs = DEFAULT_INTERVAL_MS }: AutoRefreshOptions = {},
) {
  const refreshRef = useRef(refresh);

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    let inFlight = false;

    const runRefresh = async () => {
      if (document.hidden || inFlight) {
        return;
      }

      inFlight = true;
      try {
        await refreshRef.current();
      } finally {
        inFlight = false;
      }
    };

    const intervalId = window.setInterval(() => {
      void runRefresh();
    }, intervalMs);

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        void runRefresh();
      }
    };

    const unsubscribe = subscribeToApiMutations(() => {
      void runRefresh();
    });

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      window.clearInterval(intervalId);
      unsubscribe();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [enabled, intervalMs]);
}
