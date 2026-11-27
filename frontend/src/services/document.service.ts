import { api } from "./api";
import type {
  ChunkList,
  DocumentItem,
  DocumentList,
  DocumentStatusResponse,
  DocumentUploadResponse,
} from "../types/api";

/** Must match the backend's allow-list (it also validates magic bytes server-side). */
export const ALLOWED_EXTENSIONS = ["pdf", "docx", "txt"] as const;
export const MAX_UPLOAD_MB = 25;

export function validateUpload(file: File): string | null {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!(ALLOWED_EXTENSIONS as readonly string[]).includes(ext)) {
    return `"${file.name}" is not supported. Upload PDF, DOCX or TXT files.`;
  }
  if (file.size === 0) return `"${file.name}" is empty.`;
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `"${file.name}" exceeds ${MAX_UPLOAD_MB} MB.`;
  return null;
}

export const documentService = {
  async list(limit = 100, offset = 0): Promise<DocumentList> {
    const { data } = await api.get<DocumentList>("/documents", { params: { limit, offset } });
    return data;
  },

  async get(id: string): Promise<DocumentItem> {
    const { data } = await api.get<DocumentItem>(`/documents/${id}`);
    return data;
  },

  async upload(file: File, onProgress?: (pct: number) => void): Promise<DocumentUploadResponse> {
    const form = new FormData();
    form.append("file", file);
    const { data } = await api.post<DocumentUploadResponse>("/documents/upload", form, {
      params: { auto_ingest: true },
      onUploadProgress: (e) => {
        if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100));
      },
    });
    return data;
  },

  async status(id: string): Promise<DocumentStatusResponse> {
    const { data } = await api.get<DocumentStatusResponse>(`/documents/${id}/status`);
    return data;
  },

  async chunks(id: string, limit = 50, offset = 0): Promise<ChunkList> {
    const { data } = await api.get<ChunkList>(`/documents/${id}/chunks`, { params: { limit, offset } });
    return data;
  },

  async reingest(id: string): Promise<void> {
    await api.post(`/documents/${id}/ingest`, null);
  },

  async remove(id: string): Promise<void> {
    await api.delete(`/documents/${id}`);
  },
};
