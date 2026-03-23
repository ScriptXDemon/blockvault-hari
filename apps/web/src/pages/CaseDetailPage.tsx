import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { Button, Card, DataTable, EmptyState, StatusIndicator, Modal, ModalBody, ModalFooter, Input, useToast, type ColumnDef, Breadcrumb } from "@blockvault/ui";

import { PageHeader } from "@/components/PageHeader";
import { queryClient } from "@/app/queryClient";
import { apiRequest, apiUpload } from "@/lib/api";
import { encryptFile } from "@/lib/crypto";
import { formatDateShort } from "@/lib/formatters";
import type { LegalDocumentRecord } from "@blockvault/contracts";

type DocRow = LegalDocumentRecord & Record<string, unknown>;

export function CaseDetailPage() {
  const { caseId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [uploadOpen, setUploadOpen] = useState(false);

  const caseQuery = useQuery({
    queryKey: ["case", caseId],
    queryFn: () => apiRequest<{ id: string; title: string; description: string }>(`/api/v1/cases/${caseId}`),
  });
  const documentsQuery = useQuery({
    queryKey: ["documents", caseId],
    queryFn: () => apiRequest<{ items: LegalDocumentRecord[] }>(`/api/v1/documents?caseId=${caseId}`),
  });

  const uploadMutation = useMutation({
    mutationFn: async (formData: FormData) => {
      const file = formData.get("file");
      const passphrase = String(formData.get("passphrase") ?? "");
      if (!(file instanceof File)) throw new Error("Choose a PDF to upload.");
      const init = await apiRequest<{ documentId: string; fileId: string }>(`/api/v1/documents/init-upload?caseId=${caseId}`, {
        method: "POST",
        body: JSON.stringify({ originalName: file.name, contentType: file.type || "application/pdf", size: file.size }),
      });
      const encrypted = await encryptFile(file, passphrase);
      const payload = new FormData();
      payload.append("encrypted_file", encrypted.encryptedBlob, `${file.name}.bv`);
      payload.append("algorithm", encrypted.envelope.algorithm);
      payload.append("salt_b64", encrypted.envelope.salt_b64);
      payload.append("iv_b64", encrypted.envelope.iv_b64);
      await apiUpload(`/api/v1/documents/${init.documentId}/complete-upload`, payload);
      return init.documentId;
    },
    onSuccess: async (documentId) => {
      await queryClient.invalidateQueries({ queryKey: ["documents", caseId] });
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setUploadOpen(false);
      toast.success("Document uploaded.");
      navigate(`/app/documents/${documentId}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const docs = (documentsQuery.data?.items ?? []) as DocRow[];
  const caseTitle = caseQuery.data?.title ?? "Loading...";

  const columns: ColumnDef<DocRow>[] = [
    { key: "originalName", header: "Document", sortable: true },
    { key: "status", header: "Status", render: (r) => <StatusIndicator status={r.status} /> },
    { key: "type", header: "Type", render: (r) => r.sourceDocumentId ? "Derived" : "Primary" },
    { key: "createdAt", header: "Uploaded", render: (r) => formatDateShort(r.createdAt) },
    {
      key: "_actions", header: "",
      render: (r) => (
        <div style={{ display: "flex", gap: "8px" }}>
          <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/app/documents/${r.id}`); }}>Open</Button>
          {r.evidenceBundleId && (
            <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/app/evidence/${r.evidenceBundleId}`); }}>Evidence</Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div>
      <Breadcrumb items={[{ label: "Cases", to: "/app/cases" }, { label: caseTitle }]} />
      <PageHeader
        title={caseTitle}
        description={caseQuery.data?.description || "Case-scoped documents, notarization, redaction, and custody."}
        actions={<Button onClick={() => setUploadOpen(true)}>Upload document</Button>}
      />

      <Card>
        <DataTable
          columns={columns}
          data={docs}
          getRowKey={(r) => r.id}
          loading={documentsQuery.isLoading}
          onRowClick={(r) => navigate(`/app/documents/${r.id}`)}
          emptyState={
            <EmptyState
              title="No documents yet"
              description="Upload the first legal document to begin the notarization workflow."
              action={<Button size="sm" onClick={() => setUploadOpen(true)}>Upload document</Button>}
            />
          }
        />
      </Card>

      <Modal open={uploadOpen} onClose={() => setUploadOpen(false)} title="Upload Legal Document" size="sm">
        <form onSubmit={(e) => { e.preventDefault(); void uploadMutation.mutateAsync(new FormData(e.currentTarget)); }}>
          <ModalBody>
            <div style={{ display: "grid", gap: "16px" }}>
              <Input label="Legal PDF" name="file" type="file" accept="application/pdf" required />
              <Input label="Passphrase" name="passphrase" type="password" minLength={8} required hint="Used for AES-256-GCM encryption. Store it safely." />
            </div>
          </ModalBody>
          <ModalFooter>
            <Button variant="secondary" type="button" onClick={() => setUploadOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={uploadMutation.isPending}>{uploadMutation.isPending ? "Uploading..." : "Upload"}</Button>
          </ModalFooter>
        </form>
      </Modal>
    </div>
  );
}
