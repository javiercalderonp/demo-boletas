"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Inbox, LoaderCircle } from "lucide-react";

export function DataTable({
  columns,
  rows,
  rowHrefs,
}: {
  columns: React.ReactNode[];
  rows: React.ReactNode[][];
  rowHrefs?: Array<string | null | undefined>;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [loadingHref, setLoadingHref] = useState("");
  const loadingTimeoutRef = useRef<number | null>(null);
  const navigationFallbackRef = useRef<number | null>(null);

  useEffect(() => {
    setLoadingHref("");
    if (navigationFallbackRef.current) {
      window.clearTimeout(navigationFallbackRef.current);
      navigationFallbackRef.current = null;
    }
  }, [pathname]);

  useEffect(() => {
    return () => {
      if (loadingTimeoutRef.current) {
        window.clearTimeout(loadingTimeoutRef.current);
      }
      if (navigationFallbackRef.current) {
        window.clearTimeout(navigationFallbackRef.current);
      }
    };
  }, []);

  function navigateToRow(href?: string | null) {
    if (!href) return;
    if (href === pathname) return;
    setLoadingHref(href);
    if (loadingTimeoutRef.current) {
      window.clearTimeout(loadingTimeoutRef.current);
    }
    loadingTimeoutRef.current = window.setTimeout(() => {
      setLoadingHref((currentHref) => (currentHref === href ? "" : currentHref));
    }, 8000);
    router.push(href);
    navigationFallbackRef.current = window.setTimeout(() => {
      if (window.location.pathname !== href) {
        window.location.assign(href);
      }
    }, 700);
  }

  function isInteractiveTarget(target: EventTarget | null) {
    return target instanceof HTMLElement
      ? Boolean(
          target.closest(
            "a, button, input, select, textarea, summary, [role='button']",
          ),
        )
      : false;
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-gray-200/80 bg-white shadow-sm">
      {loadingHref && (
        <div
          className="fixed bottom-5 right-5 z-50 inline-flex items-center gap-2 rounded-lg border border-primary-100 bg-white px-3.5 py-2 text-sm font-medium text-gray-700 shadow-lg"
          role="status"
          aria-live="polite"
        >
          <LoaderCircle className="h-4 w-4 animate-spin text-primary-600" />
          Cargando...
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full min-w-full">
          <thead className="bg-slate-50/80">
            <tr className="border-b border-gray-200/80">
              {columns.map((column, index) => (
                <th
                  key={index}
                  className="px-4 py-3.5 text-left text-[11px] font-semibold uppercase tracking-[0.16em] text-gray-500 first:pl-5 last:pr-5"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {rows.length ? (
              rows.map((row, index) => (
                <tr
                  key={index}
                  className={`group transition-colors hover:bg-slate-50 ${
                    rowHrefs?.[index] ? "cursor-pointer" : ""
                  } ${loadingHref === rowHrefs?.[index] ? "bg-primary-50/70" : ""}`}
                  onClick={(event) => {
                    if (loadingHref) return;
                    if (isInteractiveTarget(event.target)) return;
                    navigateToRow(rowHrefs?.[index]);
                  }}
                  onKeyDown={(event) => {
                    if (loadingHref) return;
                    if (!rowHrefs?.[index] || isInteractiveTarget(event.target)) return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      navigateToRow(rowHrefs[index]);
                    }
                  }}
                  role={rowHrefs?.[index] ? "link" : undefined}
                  tabIndex={rowHrefs?.[index] ? 0 : undefined}
                  aria-busy={loadingHref === rowHrefs?.[index] ? true : undefined}
                >
                  {row.map((cell, cellIndex) => (
                    <td
                      key={cellIndex}
                      className="px-4 py-4 align-top text-sm text-gray-700 first:pl-5 last:pr-5"
                    >
                      {loadingHref === rowHrefs?.[index] && cellIndex === 0 ? (
                        <span className="inline-flex items-center gap-2 font-medium text-primary-700">
                          <LoaderCircle className="h-4 w-4 animate-spin" />
                          Abriendo...
                        </span>
                      ) : (
                        cell
                      )}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={columns.length} className="py-14 text-center">
                  <div className="flex flex-col items-center gap-2">
                    <Inbox className="h-8 w-8 text-gray-300" />
                    <p className="text-sm text-gray-500">Sin resultados</p>
                  </div>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
