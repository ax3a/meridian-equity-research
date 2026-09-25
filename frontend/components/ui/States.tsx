"use client";

import type { ReactNode } from "react";

export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-ink-700/60 ${className}`} aria-hidden="true" />;
}

export function SkeletonLines({ count = 3, className = "" }: { count?: number; className?: string }) {
  return (
    <div className={`space-y-2 ${className}`} role="status" aria-label="Loading">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className={`h-4 ${i === count - 1 ? "w-2/3" : "w-full"}`} />
      ))}
    </div>
  );
}

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div className={`rounded-lg border border-ink-700 bg-ink-900/60 p-4 ${className}`} role="status" aria-label="Loading">
      <Skeleton className="mb-3 h-5 w-1/3" />
      <SkeletonLines count={3} />
    </div>
  );
}

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-ink-600 p-10 text-center">
      <p className="text-base font-medium text-ink-100">{title}</p>
      {description && <p className="max-w-md text-sm text-ink-300">{description}</p>}
      {action}
    </div>
  );
}

interface ErrorStateProps {
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ message, onRetry }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center gap-3 rounded-lg border border-danger/40 bg-danger/10 p-8 text-center"
    >
      <p className="font-medium text-red-300">Something went wrong</p>
      <p className="max-w-md text-sm text-red-200/80">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-red-400/50 px-3 py-1.5 text-sm font-medium text-red-200 transition hover:bg-red-500/10"
        >
          Retry
        </button>
      )}
    </div>
  );
}
