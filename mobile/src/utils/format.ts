// Mirrors frontend/components.js's idr() exactly -- same Intl.NumberFormat
// call, same locale, so numbers read identically to the web dashboard.
export function idr(value: number | string | null | undefined): string {
  return new Intl.NumberFormat("id-ID", { style: "currency", currency: "IDR", maximumFractionDigits: 0 }).format(
    Number(value || 0)
  );
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("id-ID", { day: "numeric", month: "long", year: "numeric" }).format(new Date(value));
}
