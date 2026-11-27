import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "../services/api";
import { documentService, validateUpload } from "../services/document.service";
import type { DocumentStatus } from "../types/api";

export type UploadPhase = "invalid" | "uploading" | "processing" | "indexed" | "failed" | "duplicate" | "error";

export interface UploadJob {
  key: string;
  name: string;
  size: number;
  phase: UploadPhase;
  progress: number;
  documentId?: string;
  chunks?: number;
  message?: string;
}

const POLL_MS = 1500;
const POLL_LIMIT = 400; // ~10 minutes

/**
 * Upload -> poll GET /documents/{id}/status until indexed or failed.
 * Every phase shown to the user comes from a real backend response.
 */
export function useUploads(onSettled?: () => void) {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const alive = useRef(true);
  const settledRef = useRef(onSettled);
  settledRef.current = onSettled;

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const patch = useCallback((key: string, p: Partial<UploadJob>) => {
    if (alive.current) setJobs((js) => js.map((j) => (j.key === key ? { ...j, ...p } : j)));
  }, []);

  const poll = useCallback(
    async (key: string, id: string) => {
      for (let i = 0; i < POLL_LIMIT && alive.current; i++) {
        await new Promise((r) => setTimeout(r, POLL_MS));
        try {
          const s = await documentService.status(id);
          const phase: Record<DocumentStatus, UploadPhase> = { uploaded: "processing", processing: "processing", indexed: "indexed", failed: "failed" };
          patch(key, { phase: phase[s.status], chunks: s.chunk_count, message: s.error_message ?? undefined });
          if (s.status === "indexed" || s.status === "failed") {
            settledRef.current?.();
            return;
          }
        } catch (err) {
          patch(key, { phase: "error", message: errorMessage(err) });
          return;
        }
      }
    },
    [patch],
  );

  const upload = useCallback(
    (files: File[]) => {
      files.forEach((file, idx) => {
        const key = `${Date.now()}-${idx}-${file.name}`;
        const invalid = validateUpload(file);
        setJobs((js) => [{ key, name: file.name, size: file.size, phase: invalid ? "invalid" : "uploading", progress: 0, message: invalid ?? undefined }, ...js]);
        if (invalid) return;

        documentService
          .upload(file, (pct) => patch(key, { progress: pct }))
          .then((res) => {
            const doc = res.document;
            if (res.duplicate) {
              patch(key, { phase: "duplicate", progress: 100, documentId: doc.id, chunks: doc.chunk_count, message: `Already uploaded as "${doc.filename}"` });
              settledRef.current?.();
              return;
            }
            patch(key, { phase: doc.status === "indexed" ? "indexed" : "processing", progress: 100, documentId: doc.id });
            settledRef.current?.();
            if (doc.status !== "indexed") void poll(key, doc.id);
          })
          .catch((err) => patch(key, { phase: "error", message: errorMessage(err) }));
      });
    },
    [patch, poll],
  );

  const dismiss = useCallback((key: string) => setJobs((js) => js.filter((j) => j.key !== key)), []);
  const clearFinished = useCallback(
    () => setJobs((js) => js.filter((j) => j.phase === "uploading" || j.phase === "processing")),
    [],
  );

  return { jobs, upload, dismiss, clearFinished };
}
