import * as React from "react";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost" | "destructive";
  size?: "default" | "sm" | "lg";
}

export function Button({ className = "", variant = "default", size = "default", ...props }: ButtonProps) {
  const base = "inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50";
  const variants = {
    default: "bg-primary text-primary-foreground hover:bg-primary/90 bg-blue-600 text-white hover:bg-blue-700",
    outline: "border border-input hover:bg-accent border-gray-300 hover:bg-gray-100",
    ghost: "hover:bg-accent hover:bg-gray-100",
    destructive: "bg-red-600 text-white hover:bg-red-700",
  };
  const sizes = {
    default: "h-10 px-4 py-2 text-sm",
    sm: "h-8 px-3 text-xs",
    lg: "h-12 px-6 text-base",
  };
  return (
    <button className={`${base} ${variants[variant]} ${sizes[size]} ${className}`} {...props} />
  );
}
