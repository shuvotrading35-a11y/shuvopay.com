import * as React from "react";

export function HorizontalDivider({ className = "" }: { className?: string }) {
  return <hr className={`border-t border-gray-200 ${className}`} />;
}