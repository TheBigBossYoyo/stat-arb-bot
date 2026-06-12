import { useState } from "react";
import { Button } from "./ui";

/** Dangerous-action modal: the user must type the exact phrase to proceed. */
export default function ConfirmModal({
  open, title, description, phrase, mode, onConfirm, onClose,
}: {
  open: boolean; title: string; description: string; phrase: string;
  mode: string; onConfirm: (reason: string) => void; onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  if (!open) return null;
  const matches = typed.trim() === phrase;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-md rounded-xl border border-red-500/40 bg-zinc-900 p-5 shadow-2xl">
        <div className="text-base font-semibold text-red-300">{title}</div>
        <p className="mt-2 text-sm text-zinc-300">{description}</p>
        <div className="mt-3 rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-xs text-zinc-400">
          Current mode: <span className="font-semibold text-zinc-200 uppercase">{mode}</span>.
          This action is validated again on the backend and written to the audit trail.
        </div>
        <label className="mt-4 block text-xs text-zinc-400">
          Type <span className="mono font-semibold text-red-300">{phrase}</span> to confirm
          <input
            autoFocus
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm mono text-zinc-100 outline-none focus:border-red-500"
          />
        </label>
        <label className="mt-3 block text-xs text-zinc-400">
          Reason (recorded in audit log)
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm outline-none focus:border-zinc-500"
          />
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={() => { setTyped(""); onClose(); }}>Cancel</Button>
          <Button tone="danger" disabled={!matches}
                  onClick={() => { onConfirm(reason); setTyped(""); setReason(""); }}>
            Confirm
          </Button>
        </div>
      </div>
    </div>
  );
}
