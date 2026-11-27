import { useEffect, useState, type ChangeEvent, type ReactNode } from "react";
import { CheckCircle2, RotateCcw, Save } from "lucide-react";
import { Button, Card, ErrorBanner, PageIntro, Skeleton } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useApi } from "../hooks/useApi";
import { errorMessage } from "../services/api";
import { platformService, providerOf } from "../services/platform.service";
import type { RAGSettings } from "../types/api";

function Field({ label, hint, htmlFor, children }: { label: string; hint?: ReactNode; htmlFor: string; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="label">{label}</label>
      {children}
      {hint && <p className="mt-1 text-[11px] text-subtle">{hint}</p>}
    </div>
  );
}

function Toggle({ id, checked, onChange, label }: { id: string; checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${checked ? "bg-accent" : "bg-surface-3"}`}
    >
      <span className={`inline-block size-4 rounded-full bg-white shadow transition-transform ${checked ? "translate-x-[18px]" : "translate-x-0.5"}`} />
    </button>
  );
}

export default function SettingsPage() {
  const { user } = useAuth();
  const remote = useApi(() => platformService.settings(), []);
  const models = useApi(() => platformService.models(), []);
  const [form, setForm] = useState<RAGSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (remote.data) setForm(remote.data);
  }, [remote.data]);

  const set = <K extends keyof RAGSettings>(k: K, v: RAGSettings[K]) => {
    setSaved(false);
    setForm((f) => (f ? { ...f, [k]: v } : f));
  };
  const num = (k: keyof RAGSettings) => (e: ChangeEvent<HTMLInputElement>) => set(k, Number(e.target.value) as never);
  const dirty = form && remote.data && JSON.stringify(form) !== JSON.stringify(remote.data);

  const save = async () => {
    if (!form || !remote.data) return;
    const patch: Partial<RAGSettings> = {};
    (Object.keys(form) as Array<keyof RAGSettings>).forEach((k) => {
      if (form[k] !== remote.data![k]) (patch as Record<string, unknown>)[k] = form[k];
    });
    setSaving(true);
    setError(null);
    try {
      const updated = await platformService.updateSettings(patch);
      setForm(updated);
      await remote.reload();
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageIntro
        title="Settings"
        description="Per-user retrieval and generation defaults. Chat and search use these unless a request overrides them."
        actions={
          <>
            <Button variant="secondary" icon={RotateCcw} disabled={!dirty || saving} onClick={() => remote.data && setForm(remote.data)}>Discard</Button>
            <Button icon={saved && !dirty ? CheckCircle2 : Save} disabled={!dirty} loading={saving} onClick={() => void save()}>
              {saved && !dirty ? "Saved" : "Save changes"}
            </Button>
          </>
        }
      />

      {error && <ErrorBanner className="mb-4" message={error} />}
      {remote.error && !form ? (
        <ErrorBanner message={remote.error} onRetry={() => void remote.reload()} />
      ) : !form ? (
        <div className="space-y-4"><Skeleton className="h-48 rounded-xl" /><Skeleton className="h-48 rounded-xl" /></div>
      ) : (
        <div className="space-y-6">
          <Card title="Retrieval" description="How candidate passages are found and ranked">
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Search mode" htmlFor="s-mode" hint="Hybrid fuses vector and keyword lists with RRF.">
                <select id="s-mode" className="input" value={form.search_mode} onChange={(e) => set("search_mode", e.target.value as RAGSettings["search_mode"])}>
                  <option value="hybrid">Hybrid (vector + keyword)</option>
                  <option value="vector">Vector only</option>
                  <option value="keyword">Keyword only</option>
                </select>
              </Field>
              <Field label="Top-k passages" htmlFor="s-topk" hint="1–20 passages passed to the answer stage.">
                <input id="s-topk" className="input" type="number" min={1} max={20} value={form.top_k} onChange={num("top_k")} />
              </Field>
              <Field label="Candidate multiplier" htmlFor="s-mult" hint="Candidates = top-k × multiplier before reranking.">
                <input id="s-mult" className="input" type="number" min={1} max={10} value={form.candidate_multiplier} onChange={num("candidate_multiplier")} />
              </Field>
              <Field label="Similarity threshold" htmlFor="s-sim" hint="Minimum cosine similarity for vector hits (−1 to 1).">
                <input id="s-sim" className="input" type="number" step={0.05} min={-1} max={1} value={form.similarity_threshold} onChange={num("similarity_threshold")} />
              </Field>
              <Field label="Query expansion" htmlFor="s-qe" hint="PRF reduced ranking quality on the project benchmark.">
                <select id="s-qe" className="input" value={form.query_expansion} onChange={(e) => set("query_expansion", e.target.value)}>
                  <option value="none">None</option>
                  <option value="prf">Pseudo-relevance feedback</option>
                  <option value="multi_query">LLM multi-query</option>
                </select>
              </Field>
              <Field label="Rerank min score" htmlFor="s-rms" hint="Cross-encoder logit cut-off (−20 to 20).">
                <input id="s-rms" className="input" type="number" step={0.5} min={-20} max={20} value={form.rerank_min_score} onChange={num("rerank_min_score")} />
              </Field>
              <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-surface-2/40 px-3 py-2.5 sm:col-span-2 lg:col-span-1">
                <div>
                  <div className="text-sm">Cross-encoder reranking</div>
                  <div className="text-[11px] text-subtle">More precise, adds latency</div>
                </div>
                <Toggle id="s-rerank" label="Cross-encoder reranking" checked={form.rerank} onChange={(v) => set("rerank", v)} />
              </div>
            </div>
          </Card>

          <Card title="Generation" description="Answer model and context budget">
            <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Default model" htmlFor="s-model" hint="Only providers configured on the server are selectable.">
                <select id="s-model" className="input" value={form.llm_model} onChange={(e) => set("llm_model", e.target.value)}>
                  {(models.data?.llm_allowed_models ?? [form.llm_model]).map((m) => {
                    const ok = models.data ? models.data.llm_configured_providers[providerOf(m)] : true;
                    return <option key={m} value={m} disabled={!ok}>{m === "local" ? "local (extractive, no LLM)" : m}{ok ? "" : " — not configured"}</option>;
                  })}
                </select>
              </Field>
              <Field label="Temperature" htmlFor="s-temp" hint="0–1.5. Low values keep answers close to sources.">
                <input id="s-temp" className="input" type="number" step={0.1} min={0} max={1.5} value={form.temperature} onChange={num("temperature")} />
              </Field>
              <Field label="Max output tokens" htmlFor="s-mot" hint="64–4000">
                <input id="s-mot" className="input" type="number" min={64} max={4000} value={form.max_output_tokens} onChange={num("max_output_tokens")} />
              </Field>
              <Field label="Context budget (tokens)" htmlFor="s-ctx" hint="200–12000 tokens of retrieved evidence.">
                <input id="s-ctx" className="input" type="number" min={200} max={12000} value={form.context_max_tokens} onChange={num("context_max_tokens")} />
              </Field>
              <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-surface-2/40 px-3 py-2.5 sm:col-span-2 lg:col-span-2">
                <div>
                  <div className="text-sm">Semantic answer cache</div>
                  <div className="text-[11px] text-subtle">Reuse grounded answers for near-identical stand-alone questions (cosine ≥ 0.95)</div>
                </div>
                <Toggle id="s-cache" label="Semantic answer cache" checked={form.semantic_cache} onChange={(v) => set("semantic_cache", v)} />
              </div>
            </div>
          </Card>

          <Card title="Chunking" description="Applies to documents ingested after saving; existing documents keep their chunks">
            <div className="grid gap-5 sm:grid-cols-3">
              <Field label="Strategy" htmlFor="s-cs" hint="Recursive respects sections and paragraphs.">
                <select id="s-cs" className="input" value={form.chunk_strategy} onChange={(e) => set("chunk_strategy", e.target.value)}>
                  <option value="recursive">Recursive</option>
                  <option value="sentence">Sentence</option>
                  <option value="fixed">Fixed</option>
                </select>
              </Field>
              <Field label="Chunk size (tokens)" htmlFor="s-csz" hint={models.data ? `Keep ≤ ${models.data.embedding_max_seq_length - 2} for the current embedding model.` : undefined}>
                <input id="s-csz" className="input" type="number" min={32} max={2000} value={form.chunk_size_tokens} onChange={num("chunk_size_tokens")} />
              </Field>
              <Field label="Overlap (tokens)" htmlFor="s-co" hint="0–500, must be smaller than chunk size.">
                <input id="s-co" className="input" type="number" min={0} max={500} value={form.chunk_overlap_tokens} onChange={num("chunk_overlap_tokens")} />
              </Field>
            </div>
          </Card>

          {user && (
            <Card title="Account">
              <dl className="grid gap-4 text-sm sm:grid-cols-3">
                <div><dt className="text-xs text-muted">Email</dt><dd className="mt-0.5 break-all">{user.email}</dd></div>
                <div><dt className="text-xs text-muted">Name</dt><dd className="mt-0.5">{user.full_name || "—"}</dd></div>
                <div><dt className="text-xs text-muted">Role</dt><dd className="mt-0.5 capitalize">{user.role}</dd></div>
              </dl>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
