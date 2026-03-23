import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { type LegalDocumentRecord } from "@blockvault/contracts";
import { Button, Card, Tabs, TabPanel, DataTable, EmptyState, StatusIndicator, type ColumnDef } from "@blockvault/ui";

import { PageHeader } from "@/components/PageHeader";
import { apiRequest } from "@/lib/api";
import { formatDateShort } from "@/lib/formatters";

type DocRow = LegalDocumentRecord & Record<string, unknown>;

export function DocumentsPage() {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState("primary");

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: () => apiRequest<{ items: LegalDocumentRecord[] }>("/api/v1/documents"),
  });

  const items = documentsQuery.data?.items ?? [];
  const primaryDocuments = items.filter((item) => !item.sourceDocumentId) as DocRow[];
  const redactionResults = items.filter((item) => Boolean(item.sourceDocumentId)) as DocRow[];

  const cols: ColumnDef<DocRow>[] = [
    { key: "originalName", header: "Name", sortable: true },
    { key: "status", header: "Status", render: (r) => <StatusIndicator status={r.status} /> },
    { key: "createdAt", header: "Date", sortable: true, render: (r) => formatDateShort(r.createdAt) },
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
      <PageHeader
        eyebrow="Documents"
        title="All Documents"
        description="Primary uploads stay distinct from derived redaction outputs so evidence review and proof posture remain explicit."
      />

      <Card>
        <Tabs
          tabs={[
            { id: "primary", label: "Primary Documents", badge: primaryDocuments.length },
            { id: "redactions", label: "Redaction Results", badge: redactionResults.length },
          ]}
          activeTab={activeTab}
          onChange={setActiveTab}
        />

        <TabPanel id="primary" activeTab={activeTab}>
          <DataTable
            columns={cols}
            data={primaryDocuments}
            getRowKey={(r) => r.id}
            loading={documentsQuery.isLoading}
            onRowClick={(r) => navigate(`/app/documents/${r.id}`)}
            emptyState={
              <EmptyState
                title="No primary documents yet"
                description="Upload a document from a case to begin the legal workflow."
              />
            }
          />
        </TabPanel>

        <TabPanel id="redactions" activeTab={activeTab}>
          <DataTable
            columns={[
              ...cols.slice(0, -1),
              {
                key: "source", header: "Source document",
                render: (r) => r.sourceDocumentId ? (
                  <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); navigate(`/app/documents/${r.sourceDocumentId}`); }}>
                    View source
                  </Button>
                ) : "\u2014",
              },
              cols[cols.length - 1],
            ]}
            data={redactionResults}
            getRowKey={(r) => r.id}
            loading={documentsQuery.isLoading}
            onRowClick={(r) => navigate(`/app/documents/${r.id}`)}
            emptyState={<EmptyState title="No redaction results yet" description="Run a redaction job from a document detail page to see results here." />}
          />
        </TabPanel>
      </Card>
    </div>
  );
}
