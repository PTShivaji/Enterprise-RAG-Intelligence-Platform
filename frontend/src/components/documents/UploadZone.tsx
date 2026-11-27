import { useRef, useState, type DragEvent } from "react";
import { UploadCloud } from "lucide-react";
import { ALLOWED_EXTENSIONS, MAX_UPLOAD_MB } from "../../services/document.service";
import { cx } from "../../utils/format";

export function UploadZone({ onFiles, compact }: { onFiles: (files: File[]) => void; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(files);
  };

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cx(
        "relative rounded-xl border border-dashed transition-colors",
        over ? "border-accent bg-accent-soft/50" : "border-line-strong bg-surface/50 hover:border-subtle",
        compact ? "px-4 py-6" : "px-6 py-10",
      )}
    >
      <div className="flex flex-col items-center text-center">
        <div className={cx("flex size-11 items-center justify-center rounded-xl border transition-colors", over ? "border-accent/50 bg-accent/20 text-violet-200" : "border-line bg-surface-2 text-muted")}>
          <UploadCloud className="size-5" aria-hidden />
        </div>
        <p className="mt-3 text-sm text-fg">
          <button type="button" onClick={() => input.current?.click()} className="font-medium text-violet-300 hover:text-violet-200 hover:underline">
            Choose files
          </button>{" "}
          or drag and drop
        </p>
        <p className="mt-1 text-xs text-subtle">
          {ALLOWED_EXTENSIONS.map((e) => e.toUpperCase()).join(", ")} · up to {MAX_UPLOAD_MB} MB each
        </p>
      </div>
      <input
        ref={input}
        type="file"
        multiple
        accept={ALLOWED_EXTENSIONS.map((e) => `.${e}`).join(",")}
        className="sr-only"
        aria-label="Upload documents"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) onFiles(files);
          e.target.value = "";
        }}
      />
    </div>
  );
}
