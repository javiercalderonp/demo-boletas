import type { LucideIcon } from "lucide-react";

export function StatCard({
  label,
  value,
  tone = "default",
  icon: Icon,
  className = "",
}: {
  label: string;
  value: number | string;
  tone?: "default" | "warning" | "success" | "error";
  icon?: LucideIcon;
  className?: string;
}) {
  const toneStyles = {
    default: "bg-white border-gray-200",
    warning: "bg-amber-50 border-amber-200",
    success: "bg-emerald-50 border-emerald-200",
    error: "bg-red-50 border-red-200",
  };

  const iconStyles = {
    default: "bg-primary-50 text-primary-600",
    warning: "bg-amber-100 text-amber-600",
    success: "bg-emerald-100 text-emerald-600",
    error: "bg-red-100 text-red-600",
  };

  const valueStyles = {
    default: "text-gray-900",
    warning: "text-amber-700",
    success: "text-emerald-700",
    error: "text-red-700",
  };

  return (
    <article className={`rounded-xl border p-5 shadow-sm ${toneStyles[tone]} ${className}`}>
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-500">{label}</p>
        {Icon && (
          <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${iconStyles[tone]}`}>
            <Icon className="h-5 w-5" />
          </div>
        )}
      </div>
      <p className={`mt-2 text-3xl font-bold tracking-tight ${valueStyles[tone]}`}>{value}</p>
    </article>
  );
}

export function StatCardSkeleton() {
  return (
    <article className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="skeleton h-4 w-24" />
        <div className="skeleton h-9 w-9 rounded-lg" />
      </div>
      <div className="skeleton mt-3 h-8 w-16" />
    </article>
  );
}
