"use client";

import { ReactNode, useEffect, useId, useState } from "react";
import { X } from "lucide-react";

type ImagePreviewDialogProps = {
  src: string;
  alt: string;
  children: ReactNode;
  triggerClassName?: string;
  title?: string;
};

export function ImagePreviewDialog({
  src,
  alt,
  children,
  triggerClassName,
  title = "Comprobante del gasto",
}: ImagePreviewDialogProps) {
  const [open, setOpen] = useState(false);
  const titleId = useId();

  useEffect(() => {
    if (!open) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        className={triggerClassName}
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
        aria-haspopup="dialog"
        aria-label={`Ver ${alt}`}
      >
        {children}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/75 p-4 sm:p-8"
          role="dialog"
          aria-modal="true"
          aria-labelledby={titleId}
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setOpen(false);
          }}
          onClick={(event) => event.stopPropagation()}
        >
          <div className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
            <div className="flex items-center justify-between gap-4 border-b border-gray-200 px-4 py-3 sm:px-5">
              <h2 id={titleId} className="truncate text-sm font-semibold text-gray-900">
                {title}
              </h2>
              <button
                type="button"
                className="rounded-lg p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-800 focus:outline-none focus:ring-2 focus:ring-primary-500"
                onClick={() => setOpen(false)}
                aria-label="Cerrar imagen"
                autoFocus
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-gray-100 p-3 sm:p-5">
              <img
                src={src}
                alt={alt}
                className="max-h-[calc(100vh-10rem)] max-w-full rounded-lg object-contain shadow-sm"
              />
            </div>
          </div>
        </div>
      )}
    </>
  );
}
