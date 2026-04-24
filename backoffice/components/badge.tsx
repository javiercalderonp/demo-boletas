const toneMap: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  closed: "bg-gray-100 text-gray-600 ring-gray-500/20",
  inactive: "bg-gray-100 text-gray-600 ring-gray-500/20",
  pending: "bg-amber-50 text-amber-700 ring-amber-600/20",
  pending_review: "bg-amber-50 text-amber-700 ring-amber-600/20",
  ready_to_approve: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  needs_manual_review: "bg-orange-50 text-orange-700 ring-orange-600/20",
  observed: "bg-purple-50 text-purple-700 ring-purple-600/20",
  approved: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  rejected: "bg-red-50 text-red-700 ring-red-600/20",
  in_progress: "bg-blue-50 text-blue-700 ring-blue-600/20",
  open: "bg-blue-50 text-blue-700 ring-blue-600/20",
  pending_user_confirmation: "bg-purple-50 text-purple-700 ring-purple-600/20",
};

const defaultTone = "bg-gray-100 text-gray-600 ring-gray-500/20";

export function Badge({
  children,
  tone,
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  const key = (tone ?? (typeof children === "string" ? children : "")).toLowerCase();
  const style = toneMap[key] || defaultTone;

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {children}
    </span>
  );
}
