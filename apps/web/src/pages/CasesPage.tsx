import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { Button, Card, EmptyState, Modal, ModalBody, ModalFooter, Input, Textarea, useToast } from "@blockvault/ui";

import { PageHeader } from "@/components/PageHeader";
import { queryClient } from "@/app/queryClient";
import { apiRequest } from "@/lib/api";
import { formatDateShort } from "@/lib/formatters";
import styles from "./CasesPage.module.css";

type CaseItem = { id: string; title: string; description: string; createdAt: string };

export function CasesPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const casesQuery = useQuery({
    queryKey: ["cases"],
    queryFn: () => apiRequest<{ items: CaseItem[] }>("/api/v1/cases"),
  });

  const createCaseMutation = useMutation({
    mutationFn: (payload: { title: string; description: string }) =>
      apiRequest<{ id: string }>("/api/v1/cases", { method: "POST", body: JSON.stringify(payload) }),
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({ queryKey: ["cases"] });
      setCreateOpen(false);
      setTitle("");
      setDescription("");
      toast.success("Case created successfully.");
      navigate(`/app/cases/${data.id}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const cases = casesQuery.data?.items ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Legal cases"
        title="Cases"
        description="Structure legal work around matters. Each case is the source of truth for documents, notarization, and custody history."
        actions={<Button onClick={() => setCreateOpen(true)}>New case</Button>}
      />

      {cases.length === 0 && !casesQuery.isLoading ? (
        <Card>
          <EmptyState
            title="No cases yet"
            description="Create your first case to begin organizing legal documents, notarizations, and evidence exports."
            action={<Button onClick={() => setCreateOpen(true)}>Create first case</Button>}
          />
        </Card>
      ) : (
        <div className={styles.grid}>
          {cases.map((c) => (
            <button key={c.id} className={styles.card} onClick={() => navigate(`/app/cases/${c.id}`)}>
              <div className={styles.cardEyebrow}>Created {formatDateShort(c.createdAt)}</div>
              <div className={styles.cardTitle}>{c.title}</div>
              <p className={styles.cardDesc}>{c.description || "No description provided."}</p>
              <div className={styles.cardArrow}>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>
                </svg>
              </div>
            </button>
          ))}
        </div>
      )}

      <Modal open={createOpen} onClose={() => setCreateOpen(false)} title="Create New Case" size="sm">
        <form onSubmit={(e) => { e.preventDefault(); void createCaseMutation.mutateAsync({ title, description }); }}>
          <ModalBody>
            <div style={{ display: "grid", gap: "16px" }}>
              <Input label="Case title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g., Smith v. Doe" required minLength={3} autoFocus />
              <Textarea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Brief description of the matter..." rows={3} />
            </div>
          </ModalBody>
          <ModalFooter>
            <Button variant="secondary" type="button" onClick={() => setCreateOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={!title || createCaseMutation.isPending}>{createCaseMutation.isPending ? "Creating..." : "Create case"}</Button>
          </ModalFooter>
        </form>
      </Modal>
    </div>
  );
}
