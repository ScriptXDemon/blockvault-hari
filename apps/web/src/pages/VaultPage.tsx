import { useState, useRef } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  Button, Card, Tabs, TabPanel, DataTable, EmptyState,
  DropdownMenu, Modal, ModalBody, ModalFooter, Input, useToast,
  type ColumnDef,
} from "@blockvault/ui";

import { PageHeader } from "@/components/PageHeader";
import { queryClient } from "@/app/queryClient";
import { apiBinary, apiRequest, apiUpload } from "@/lib/api";
import { decryptBlob, downloadBlob, encryptFile } from "@/lib/crypto";
import { formatDateShort, formatBytes, truncateWallet } from "@/lib/formatters";

type VaultFile = { id: string; originalName: string; createdAt: string; size: number; sharedWith: string[] };
type Share = { id: string; originalName: string; ownerWallet?: string; recipientWallet?: string; fileId?: string; createdAt: string };

const FILE_COLS: ColumnDef<VaultFile & Record<string, unknown>>[] = [
  { key: "originalName", header: "Name", sortable: true },
  { key: "size", header: "Size", render: (r) => formatBytes(r.size) },
  { key: "createdAt", header: "Uploaded", sortable: true, render: (r) => formatDateShort(r.createdAt) },
  { key: "sharedWith", header: "Shared with", render: (r) => r.sharedWith.length ? `${r.sharedWith.length} wallet${r.sharedWith.length > 1 ? "s" : ""}` : "\u2014" },
];

const SHARE_COLS: ColumnDef<Share & Record<string, unknown>>[] = [
  { key: "originalName", header: "File name", sortable: true },
  { key: "wallet", header: "Wallet", render: (r) => truncateWallet((r.ownerWallet ?? r.recipientWallet ?? "") as string) },
  { key: "createdAt", header: "Date", render: (r) => formatDateShort(r.createdAt) },
];

export function VaultPage() {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState("my-files");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [passphraseTarget, setPassphraseTarget] = useState<{ fileId: string; name: string } | null>(null);
  const [shareTarget, setShareTarget] = useState<{ fileId: string; name: string } | null>(null);
  const [downloadPassphrase, setDownloadPassphrase] = useState("");
  const [recipientWallet, setRecipientWallet] = useState("");
  const uploadFormRef = useRef<HTMLFormElement>(null);

  const filesQuery = useQuery({ queryKey: ["vault-files"], queryFn: () => apiRequest<{ items: VaultFile[] }>("/api/v1/files") });
  const incomingQuery = useQuery({ queryKey: ["incoming-shares"], queryFn: () => apiRequest<{ items: Share[] }>("/api/v1/shares/incoming") });
  const outgoingQuery = useQuery({ queryKey: ["outgoing-shares"], queryFn: () => apiRequest<{ items: Share[] }>("/api/v1/shares/outgoing") });

  const uploadMutation = useMutation({
    mutationFn: async (formData: FormData) => {
      const file = formData.get("file");
      const passphrase = String(formData.get("passphrase") ?? "");
      if (!(file instanceof File)) throw new Error("Select a file first.");
      const init = await apiRequest<{ fileId: string }>("/api/v1/files/init-upload", {
        method: "POST",
        body: JSON.stringify({ originalName: file.name, contentType: file.type || "application/octet-stream", size: file.size }),
      });
      const encrypted = await encryptFile(file, passphrase);
      const payload = new FormData();
      payload.append("encrypted_file", encrypted.encryptedBlob, `${file.name}.bv`);
      payload.append("algorithm", encrypted.envelope.algorithm);
      payload.append("salt_b64", encrypted.envelope.salt_b64);
      payload.append("iv_b64", encrypted.envelope.iv_b64);
      await apiUpload(`/api/v1/files/${init.fileId}/complete-upload`, payload);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vault-files"] });
      setUploadOpen(false);
      uploadFormRef.current?.reset();
      toast.success("File encrypted and uploaded.");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteMutation = useMutation({
    mutationFn: (fileId: string) => apiRequest(`/api/v1/files/${fileId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vault-files"] });
      await queryClient.invalidateQueries({ queryKey: ["outgoing-shares"] });
      toast.success("File deleted and shares revoked.");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const revokeMutation = useMutation({
    mutationFn: (shareId: string) => apiRequest(`/api/v1/shares/${shareId}`, { method: "DELETE" }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["vault-files"] });
      await queryClient.invalidateQueries({ queryKey: ["incoming-shares"] });
      await queryClient.invalidateQueries({ queryKey: ["outgoing-shares"] });
      toast.success("Share revoked.");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const shareMutation = useMutation({
    mutationFn: async ({ fileId, wallet }: { fileId: string; wallet: string }) => {
      await apiRequest(`/api/v1/files/${fileId}/share`, { method: "POST", body: JSON.stringify({ recipientWallet: wallet }) });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["outgoing-shares"] });
      await queryClient.invalidateQueries({ queryKey: ["vault-files"] });
      setShareTarget(null);
      setRecipientWallet("");
      toast.success("File shared successfully.");
    },
    onError: (e: Error) => toast.error(e.message),
  });

  async function handleDownload(fileId: string) {
    if (!downloadPassphrase) return;
    try {
      const response = await apiBinary(`/api/v1/files/${fileId}/download`);
      const encrypted = await response.blob();
      const decrypted = await decryptBlob(
        encrypted, downloadPassphrase,
        response.headers.get("X-BlockVault-Salt") ?? "",
        response.headers.get("X-BlockVault-Iv") ?? "",
      );
      downloadBlob(decrypted, response.headers.get("X-BlockVault-Original-Name") ?? "blockvault-file");
      setPassphraseTarget(null);
      setDownloadPassphrase("");
      toast.success("File downloaded successfully.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Download failed.");
    }
  }

  const files = (filesQuery.data?.items ?? []) as (VaultFile & Record<string, unknown>)[];
  const incoming = (incomingQuery.data?.items ?? []) as (Share & Record<string, unknown>)[];
  const outgoing = (outgoingQuery.data?.items ?? []) as (Share & Record<string, unknown>)[];

  return (
    <div>
      <PageHeader
        eyebrow="Private vault"
        title="Encrypted Storage"
        description="Files are encrypted in the browser, stored as opaque blobs, and shared by explicit wallet-based ACLs."
        actions={<Button onClick={() => setUploadOpen(true)}>Upload file</Button>}
      />

      <Card>
        <Tabs
          tabs={[
            { id: "my-files", label: "My Files", badge: files.length },
            { id: "incoming", label: "Incoming Shares", badge: incoming.length },
            { id: "outgoing", label: "Outgoing Shares", badge: outgoing.length },
          ]}
          activeTab={activeTab}
          onChange={setActiveTab}
        />

        <TabPanel id="my-files" activeTab={activeTab}>
          <DataTable
            columns={[
              ...FILE_COLS,
              {
                key: "_actions", header: "",
                render: (r) => (
                  <DropdownMenu
                    trigger={<Button variant="ghost" size="sm">Actions</Button>}
                    items={[
                      { label: "Download", onClick: () => setPassphraseTarget({ fileId: r.id, name: r.originalName }) },
                      { label: "Share", onClick: () => setShareTarget({ fileId: r.id, name: r.originalName }) },
                      { divider: true, label: "", onClick: () => {} },
                      { label: "Delete", variant: "danger", onClick: () => void deleteMutation.mutateAsync(r.id) },
                    ]}
                  />
                ),
              },
            ]}
            data={files}
            getRowKey={(r) => r.id}
            loading={filesQuery.isLoading}
            emptyState={
              <EmptyState
                title="No files uploaded yet"
                description="Encrypt and upload your first file to the vault."
                action={<Button size="sm" onClick={() => setUploadOpen(true)}>Upload file</Button>}
              />
            }
          />
        </TabPanel>

        <TabPanel id="incoming" activeTab={activeTab}>
          <DataTable
            columns={[
              ...SHARE_COLS,
              {
                key: "_actions", header: "",
                render: (r) => (
                  <Button variant="ghost" size="sm" onClick={() => setPassphraseTarget({ fileId: r.fileId as string, name: r.originalName })}>
                    Download
                  </Button>
                ),
              },
            ]}
            data={incoming}
            getRowKey={(r) => r.id}
            loading={incomingQuery.isLoading}
            emptyState={<EmptyState title="No incoming shares" description="Nothing has been shared with your wallet yet." />}
          />
        </TabPanel>

        <TabPanel id="outgoing" activeTab={activeTab}>
          <DataTable
            columns={[
              ...SHARE_COLS,
              {
                key: "_actions", header: "",
                render: (r) => (
                  <Button variant="danger" size="sm" onClick={() => void revokeMutation.mutateAsync(r.id)} disabled={revokeMutation.isPending}>
                    Revoke
                  </Button>
                ),
              },
            ]}
            data={outgoing}
            getRowKey={(r) => r.id}
            loading={outgoingQuery.isLoading}
            emptyState={<EmptyState title="No outgoing shares" description="You have no active outgoing file shares." />}
          />
        </TabPanel>
      </Card>

      <Modal open={uploadOpen} onClose={() => setUploadOpen(false)} title="Upload Encrypted File" size="sm">
        <form ref={uploadFormRef} onSubmit={(e) => { e.preventDefault(); void uploadMutation.mutateAsync(new FormData(e.currentTarget)); }}>
          <ModalBody>
            <div style={{ display: "grid", gap: "16px" }}>
              <Input label="File" name="file" type="file" required />
              <Input label="Passphrase" name="passphrase" type="password" minLength={8} required hint="Used for AES-256-GCM encryption. Store it safely." />
            </div>
          </ModalBody>
          <ModalFooter>
            <Button variant="secondary" type="button" onClick={() => setUploadOpen(false)}>Cancel</Button>
            <Button type="submit" disabled={uploadMutation.isPending}>{uploadMutation.isPending ? "Encrypting..." : "Upload & Encrypt"}</Button>
          </ModalFooter>
        </form>
      </Modal>

      <Modal open={!!passphraseTarget} onClose={() => { setPassphraseTarget(null); setDownloadPassphrase(""); }} title="Enter Passphrase to Decrypt" size="sm">
        <ModalBody>
          <p style={{ margin: "0 0 16px", fontSize: "var(--bv-text-sm)", color: "var(--bv-ink-muted)" }}>
            Enter the passphrase used when <strong>{passphraseTarget?.name}</strong> was uploaded.
          </p>
          <Input label="Passphrase" type="password" value={downloadPassphrase} onChange={(e) => setDownloadPassphrase(e.target.value)} autoFocus />
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" onClick={() => { setPassphraseTarget(null); setDownloadPassphrase(""); }}>Cancel</Button>
          <Button disabled={!downloadPassphrase} onClick={() => passphraseTarget && void handleDownload(passphraseTarget.fileId)}>Download</Button>
        </ModalFooter>
      </Modal>

      <Modal open={!!shareTarget} onClose={() => { setShareTarget(null); setRecipientWallet(""); }} title="Share File" size="sm">
        <ModalBody>
          <p style={{ margin: "0 0 16px", fontSize: "var(--bv-text-sm)", color: "var(--bv-ink-muted)" }}>
            Share <strong>{shareTarget?.name}</strong> with another wallet address.
          </p>
          <Input label="Recipient wallet address" placeholder="0x..." value={recipientWallet} onChange={(e) => setRecipientWallet(e.target.value)} autoFocus />
        </ModalBody>
        <ModalFooter>
          <Button variant="secondary" onClick={() => { setShareTarget(null); setRecipientWallet(""); }}>Cancel</Button>
          <Button
            disabled={!recipientWallet || shareMutation.isPending}
            onClick={() => shareTarget && void shareMutation.mutateAsync({ fileId: shareTarget.fileId, wallet: recipientWallet })}
          >
            {shareMutation.isPending ? "Sharing..." : "Share"}
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
}
