import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

import { chromium } from "playwright";

const WEB_URL = (process.env.E2E_WEB_URL ?? "http://127.0.0.1:4173").replace(/\/+$/, "");
const API_URL = (process.env.E2E_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const HEADLESS = process.env.E2E_HEADLESS !== "false";
const ARTIFACT_DIR = path.resolve(process.cwd(), "output", "playwright");
const PASSPHRASE = "playwright-passphrase-123";
const OWNER_WALLET = "0x1000000000000000000000000000000000000001";
const RECIPIENT_WALLET = "0x2000000000000000000000000000000000000002";

const PDF_BASE64 =
  "JVBERi0xLjMKJZOMi54gUmVwb3J0TGFiIEdlbmVyYXRlZCBQREYgZG9jdW1lbnQgKG9wZW5zb3VyY2UpCjEgMCBvYmoKPDwKL0YxIDIgMCBSCj4+CmVuZG9iagoyIDAgb2JqCjw8Ci9CYXNlRm9udCAvSGVsdmV0aWNhIC9FbmNvZGluZyAvV2luQW5zaUVuY29kaW5nIC9OYW1lIC9GMSAvU3VidHlwZSAvVHlwZTEgL1R5cGUgL0ZvbnQKPj4KZW5kb2JqCjMgMCBvYmoKPDwKL0NvbnRlbnRzIDcgMCBSIC9NZWRpYUJveCBbIDAgMCA2MTIgNzkyIF0gL1BhcmVudCA2IDAgUiAvUmVzb3VyY2VzIDw8Ci9Gb250IDEgMCBSIC9Qcm9jU2V0IFsgL1BERiAvVGV4dCAvSW1hZ2VCIC9JbWFnZUMgL0ltYWdlSSBdCj4+IC9Sb3RhdGUgMCAvVHJhbnMgPDwKCj4+IAogIC9UeXBlIC9QYWdlCj4+CmVuZG9iago0IDAgb2JqCjw8Ci9QYWdlTW9kZSAvVXNlTm9uZSAvUGFnZXMgNiAwIFIgL1R5cGUgL0NhdGFsb2cKPj4KZW5kb2JqCjUgMCBvYmoKPDwKL0F1dGhvciAoYW5vbnltb3VzKSAvQ3JlYXRpb25EYXRlIChEOjIwMjYwMzEyMjEyNzQwKzA1JzAwJykgL0NyZWF0b3IgKGFub255bW91cykgL0tleXdvcmRzICgpIC9Nb2REYXRlIChEOjIwMjYwMzEyMjEyNzQwKzA1JzAwJykgL1Byb2R1Y2VyIChSZXBvcnRMYWIgUERGIExpYnJhcnkgLSBcKG9wZW5zb3VyY2VcKSkgCiAgL1N1YmplY3QgKHVuc3BlY2lmaWVkKSAvVGl0bGUgKHVudGl0bGVkKSAvVHJhcHBlZCAvRmFsc2UKPj4KZW5kb2JqCjYgMCBvYmoKPDwKL0NvdW50IDEgL0tpZHMgWyAzIDAgUiBdIC9UeXBlIC9QYWdlcwo+PgplbmRvYmoKNyAwIG9iago8PAovRmlsdGVyIFsgL0FTQ0lJODVEZWNvZGUgL0ZsYXRlRGVjb2RlIF0gL0xlbmd0aCAxODYKPj4Kc3RyZWFtCkdhclcwNFVdK1wmO0tyWU1LYCRUUlpyRV5mTVgoJUxWbDlOQm8xdTExRFRsXyMnRm1INCElXjdtTilbMzdfWWliY2szXGskLydoVWFMNXRQN2dyQF4/QEdbbzlqJU1mPUluKyRYWVs6JDs1YkpJYihhYT47ZTB1JmxLX1MpL3FfRUlGTEVuSFJwMz0wWTFLPFNCXzA3cjU0MVRlVHVgRFZyN2tlLC4lZCJxKyQnOzRVM1ppMSQ4b1V+PmVuZHN0cmVhbQplbmRvYmoKeHJlZgowIDgKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDYxIDAwMDAwIG4gCjAwMDAwMDAwOTIgMDAwMDAgbiAKMDAwMDAwMDE5OSAwMDAwMCBuIAowMDAwMDAwMzkyIDAwMDAwIG4gCjAwMDAwMDA0NjAgMDAwMDAgbiAKMDAwMDAwMDcyMSAwMDAwMCBuIAowMDAwMDAwNzgwIDAwMDAwIG4gCnRyYWlsZXIKPDwKL0lEIApbPDkzYzQ2MGRlNzAxODlkYjYwNmNlNTg4NjY1YjM1YjgxPjw5M2M0NjBkZTcwMTg5ZGI2MDZjZTU4ODY2NWIzNWI4MT5dCiUgUmVwb3J0TGFiIGdlbmVyYXRlZCBQREYgZG9jdW1lbnQgLS0gZGlnZXN0IChvcGVuc291cmNlKQoKL0luZm8gNSAwIFIKL1Jvb3QgNCAwIFIKL1NpemUgOAo+PgpzdGFydHhyZWYKMTA1NgolJUVPRgo=";

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

async function ensureResponseOk(response, label) {
  assert(response.ok(), `${label} failed with ${response.status()} ${response.statusText()}`);
  return response;
}

async function readJson(response, label) {
  await ensureResponseOk(response, label);
  return response.json();
}

function shouldIgnoreConsoleError(text) {
  return text.includes("/api/auth/me") && text.includes("401");
}

function attachConsoleCollector(page, consoleErrors) {
  page.on("console", (message) => {
    if (message.type() !== "error") {
      return;
    }
    const text = message.text();
    if (shouldIgnoreConsoleError(text)) {
      return;
    }
    consoleErrors.push(text);
  });
}

async function waitForPageReady(page) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForTimeout(250);
}

async function loginWithTestAuth(page, walletAddress, displayName) {
  const response = await page.context().request.post(`${API_URL}/api/auth/test-login`, {
    data: { walletAddress, displayName },
  });
  await ensureResponseOk(response, "Test login");
}

async function setFileInput(locator, name, mimeType, content) {
  await locator.setInputFiles({
    name,
    mimeType,
    buffer: Buffer.from(content),
  });
}

async function takeShot(page, filename) {
  await page.screenshot({ path: path.join(ARTIFACT_DIR, filename), fullPage: true });
}

function getRedactionTimeoutMs(statusPayload) {
  const proofTimeoutSeconds = statusPayload?.zkpt_runtime?.limits?.proofTimeoutSeconds ?? 360;
  return Math.max((proofTimeoutSeconds + 120) * 1000, 6 * 60 * 1000);
}

async function verifyServedBuild(page) {
  const servedBuildMetaResponse = await page.context().request.get(`${WEB_URL}/build-meta.json`);
  const servedBuildMeta = await readJson(servedBuildMetaResponse, "Served build metadata");

  const buildStamp = page.getByTestId("build-id");
  await buildStamp.waitFor({ timeout: 10_000 });
  const buildStampText = (await buildStamp.textContent()) ?? "";
  assert(buildStampText.includes(servedBuildMeta.buildId), "Visible build id did not match served build metadata");

  return servedBuildMeta;
}

async function createVaultFileFlow(page, runId) {
  const fileName = `vault-fixture-${runId}.txt`;

  await page.goto(`${WEB_URL}/app/vault`);
  await waitForPageReady(page);

  await page.getByRole("button", { name: "Upload file" }).first().click();
  const uploadDialog = page.locator('[role="dialog"]').filter({ hasText: "Upload Encrypted File" });
  await uploadDialog.waitFor({ timeout: 10_000 });
  await setFileInput(uploadDialog.locator('input[type="file"]'), fileName, "text/plain", `Vault workflow fixture ${runId}`);
  await uploadDialog.locator('input[type="password"]').fill(PASSPHRASE);
  await uploadDialog.getByRole("button", { name: "Upload & Encrypt" }).click();
  await page.getByText("File encrypted and uploaded.").waitFor({ timeout: 10_000 });

  const filesPayload = await readJson(await page.context().request.get(`${API_URL}/api/v1/files`), "List vault files");
  const fileRecord = filesPayload.items.find((item) => item.originalName === fileName);
  assert(fileRecord, `Vault file ${fileName} was not returned by the API`);

  const vaultRow = page.getByRole("row", { name: new RegExp(fileName, "i") }).first();
  await vaultRow.getByRole("button", { name: "Actions" }).click();
  await page.getByRole("button", { name: "Share" }).click();
  const shareDialog = page.locator('[role="dialog"]').filter({ hasText: "Share File" });
  await shareDialog.locator('input[placeholder="0x..."]').fill(RECIPIENT_WALLET);
  await shareDialog.getByRole("button", { name: "Share" }).click();
  await page.getByText("File shared successfully.").waitFor({ timeout: 10_000 });

  const outgoingPayload = await readJson(await page.context().request.get(`${API_URL}/api/v1/shares/outgoing`), "List outgoing shares");
  const shareRecord = outgoingPayload.items.find((item) => item.fileId === fileRecord.id && item.recipientWallet === RECIPIENT_WALLET.toLowerCase());
  assert(shareRecord, "Vault share record was not created");

  await takeShot(page, "vault-owner-flow.png");
  return {
    fileId: fileRecord.id,
    fileName,
    shareId: shareRecord.id,
  };
}

async function verifyRecipientShareFlow(browser, shareState, consoleErrors) {
  const recipientContext = await browser.newContext({ acceptDownloads: true });
  const recipientPage = await recipientContext.newPage();
  attachConsoleCollector(recipientPage, consoleErrors);

  try {
    const health = await recipientContext.request.get(`${API_URL}/health`);
    await ensureResponseOk(health, "API health check (recipient)");

    await loginWithTestAuth(recipientPage, RECIPIENT_WALLET, "Playwright Recipient");
    await recipientPage.goto(`${WEB_URL}/app/vault`);
    await waitForPageReady(recipientPage);

    await recipientPage.getByRole("tab", { name: /Incoming Shares/i }).click();
    const incomingRow = recipientPage.getByRole("row", { name: new RegExp(shareState.fileName, "i") }).first();
    await incomingRow.waitFor({ timeout: 10_000 });

    const downloadResponse = await recipientContext.request.get(`${API_URL}/api/v1/files/${shareState.fileId}/download`);
    await ensureResponseOk(downloadResponse, "Recipient shared file download");
    const contentType = downloadResponse.headers()["content-type"] ?? "";
    assert(contentType.includes("application/octet-stream"), `Unexpected shared download content-type: ${contentType}`);
    const body = await downloadResponse.body();
    assert(body.length > 0, "Recipient shared file download was empty");

    await takeShot(recipientPage, "vault-recipient-flow.png");
  } finally {
    await recipientContext.close();
  }
}

async function revokeShare(page, shareState) {
  await page.goto(`${WEB_URL}/app/vault`);
  await waitForPageReady(page);
  await page.getByRole("tab", { name: /Outgoing Shares/i }).click();

  const revokeResponse = await page.context().request.delete(`${API_URL}/api/v1/shares/${shareState.shareId}`);
  await ensureResponseOk(revokeResponse, "Revoke outgoing share");
  await page.reload();
  await waitForPageReady(page);
  await page.getByRole("tab", { name: /Outgoing Shares/i }).click();

  const outgoingPayload = await readJson(await page.context().request.get(`${API_URL}/api/v1/shares/outgoing`), "List outgoing shares after revoke");
  assert(!outgoingPayload.items.some((item) => item.id === shareState.shareId), "Revoked share still appears in outgoing shares");
  assert(
    !(await page.getByRole("row", { name: new RegExp(shareState.fileName, "i") }).count()),
    "Revoked share still appears in the outgoing shares UI",
  );

  const revokeDownload = await page.context().request.post(`${API_URL}/api/auth/test-login`, {
    data: { walletAddress: RECIPIENT_WALLET, displayName: "Playwright Recipient" },
  });
  await ensureResponseOk(revokeDownload, "Recipient re-login after revoke");
  const revokedDownloadResponse = await page.context().request.get(`${API_URL}/api/v1/files/${shareState.fileId}/download`);
  assert(revokedDownloadResponse.status() === 403, `Expected revoked recipient download to return 403, got ${revokedDownloadResponse.status()}`);

  await loginWithTestAuth(page, OWNER_WALLET, "Playwright User");
  await takeShot(page, "vault-share-revoked.png");
}

async function deleteVaultFile(page, shareState) {
  await page.goto(`${WEB_URL}/app/vault`);
  await waitForPageReady(page);

  const vaultRow = page.getByRole("row", { name: new RegExp(shareState.fileName, "i") }).first();
  await vaultRow.waitFor({ timeout: 10_000 });
  await vaultRow.getByRole("button", { name: "Actions" }).click();
  await page.getByRole("button", { name: "Delete" }).click();
  await page.getByText("File deleted and shares revoked.").waitFor({ timeout: 10_000 });

  const filesPayload = await readJson(await page.context().request.get(`${API_URL}/api/v1/files`), "List vault files after delete");
  assert(!filesPayload.items.some((item) => item.id === shareState.fileId), "Deleted vault file still appears in the API listing");
  await takeShot(page, "vault-file-deleted.png");
}

async function createCaseAndDocumentFlow(page, runId) {
  const caseTitle = `Matter ${runId}`;
  const legalFileName = `legal-fixture-${runId}.pdf`;

  await page.goto(`${WEB_URL}/app/cases`);
  await waitForPageReady(page);

  await page.getByRole("button", { name: /New case|Create first case/i }).click();
  const caseDialog = page.locator('[role="dialog"]').filter({ hasText: "Create New Case" });
  await caseDialog.locator('input[placeholder*="Smith"]').fill(caseTitle);
  await caseDialog.locator('textarea[placeholder*="Brief description"]').fill("Local Playwright workflow coverage.");
  await caseDialog.getByRole("button", { name: "Create case" }).click();

  await page.waitForURL(/\/app\/cases\/([^/?#]+)/i, { timeout: 15_000 });
  const caseId = page.url().match(/\/app\/cases\/([^/?#]+)/i)?.[1];
  assert(caseId, "Case page URL did not contain a case id");

  await page.getByRole("button", { name: "Upload document" }).first().click();
  const uploadDialog = page.locator('[role="dialog"]').filter({ hasText: "Upload Legal Document" });
  await uploadDialog.locator('input[type="file"]').setInputFiles({
    name: legalFileName,
    mimeType: "application/pdf",
    buffer: Buffer.from(PDF_BASE64, "base64"),
  });
  await uploadDialog.locator('input[type="password"]').fill(PASSPHRASE);
  await uploadDialog.getByRole("button", { name: "Upload" }).click();
  await page.waitForURL(/\/app\/documents\/doc_/i, { timeout: 15_000 });
  await waitForPageReady(page);
  await takeShot(page, "document-uploaded.png");

  const sourceDocumentId = page.url().match(/\/app\/documents\/([^/?#]+)/i)?.[1];
  assert(sourceDocumentId, "Document page URL did not contain a document id");
  return {
    caseId,
    caseTitle,
    legalFileName,
    sourceDocumentId,
  };
}

async function notarizeEvidenceFlow(page) {
  await page.locator('input[type="password"]').first().fill(PASSPHRASE);
  await page.getByRole("button", { name: "Notarize Document" }).click();
  await page.getByText("Document notarized and linked to a fresh evidence bundle.").waitFor({ timeout: 10_000 });
  await page.getByText("Document notarized and evidence bundle issued").waitFor({ timeout: 10_000 });
  await takeShot(page, "document-notarized.png");

  const evidenceButton = page.getByRole("button", { name: "Evidence" });
  await evidenceButton.click();
  await page.waitForURL(/\/app\/evidence\/([^/?#]+)/i, { timeout: 15_000 });
  await page.getByRole("button", { name: "Download ZIP" }).waitFor({ timeout: 10_000 });
  await page.getByText("Evidence bundle created").waitFor({ timeout: 10_000 });
  await takeShot(page, "evidence-page.png");

  const bundleId = page.url().match(/\/app\/evidence\/([^/?#]+)/i)?.[1];
  assert(bundleId, "Evidence page URL did not contain a bundle id");

  const previewPayload = await readJson(await page.context().request.get(`${API_URL}/api/v1/evidence/${bundleId}`), "Evidence bundle preview");
  assert(Array.isArray(previewPayload.chainOfCustody), "Evidence preview did not include chain-of-custody data");
  assert(
    previewPayload.chainOfCustody.some((event) => event.summary === "Document notarized and evidence bundle issued"),
    "Evidence preview missing the document notarization custody event",
  );
  assert(
    previewPayload.chainOfCustody.some((event) => event.summary === "Evidence bundle created"),
    "Evidence preview missing the evidence bundle creation event",
  );

  const exportResponse = await page.context().request.get(`${API_URL}/api/v1/evidence/${bundleId}/export`);
  await ensureResponseOk(exportResponse, "Evidence export");
  const exportContentType = exportResponse.headers()["content-type"] ?? "";
  assert(exportContentType.includes("application/zip"), `Unexpected evidence export content-type: ${exportContentType}`);
  const exportBody = await exportResponse.body();
  assert(exportBody.length > 0, "Evidence export ZIP was empty");

  return bundleId;
}

async function redactionFlow(page, timeoutMs) {
  await page.goBack();
  await page.waitForURL(/\/app\/documents\/doc_/i, { timeout: 15_000 });
  await waitForPageReady(page);
  await page.locator('input[type="password"]').first().fill(PASSPHRASE);
  await page.getByPlaceholder("Type a term and press Enter...").fill("Privileged");
  await page.getByRole("button", { name: "Add" }).click();
  await page.getByRole("button", { name: "Create Redaction" }).click();

  const startedAt = Date.now();
  for (;;) {
    if (Date.now() - startedAt > timeoutMs) {
      throw new Error("Redaction workflow did not reach a terminal browser state within the timeout");
    }

    const currentUrl = page.url();
    if (/\/app\/documents\/docr_/i.test(currentUrl)) {
      const resultDocumentId = currentUrl.match(/\/app\/documents\/([^/?#]+)/i)?.[1];
      assert(resultDocumentId, "Redaction result URL did not contain a document id");
      await page.getByText("Verified", { exact: true }).waitFor({ timeout: 10_000 });
      await page.getByRole("button", { name: /Show raw JSON|Hide raw JSON/i }).click();
      const zkptJson = await page.locator("pre").first().textContent();
      assert(zkptJson?.includes('"status": "verified"'), "Redaction result page did not render a verified ZKPT payload");
      await takeShot(page, "redaction-result.png");
      return resultDocumentId;
    }

    const notices = await page.locator(".notice").allTextContents();
    if (notices.some((text) => /timed out|failed/i.test(text))) {
      throw new Error(`Redaction browser flow failed: ${notices.join(" | ")}`);
    }

    await page.waitForTimeout(1_000);
  }
}

async function deleteSourceDocumentFlow(page, documentState, evidenceBundleId, redactionDocumentId) {
  await page.getByRole("button", { name: "View source" }).click();
  await page.waitForURL(new RegExp(`/app/documents/${documentState.sourceDocumentId}`, "i"), { timeout: 15_000 });
  await waitForPageReady(page);

  await page.getByRole("button", { name: "Delete" }).click();
  const deleteDialog = page.locator('[role="dialog"]').filter({ hasText: "Delete Document?" });
  await deleteDialog.getByRole("button", { name: "Delete permanently" }).click();
  await page.waitForURL(new RegExp(`/app/cases/${documentState.caseId}`, "i"), { timeout: 15_000 });
  await waitForPageReady(page);

  const caseDocuments = await readJson(
    await page.context().request.get(`${API_URL}/api/v1/documents?caseId=${documentState.caseId}`),
    "List case documents after source delete",
  );
  assert(
    !caseDocuments.items.some((item) => item.id === documentState.sourceDocumentId || item.id === redactionDocumentId),
    "Deleted document lineage still appears in the case documents API",
  );
  assert(!(await page.locator(".list-row").filter({ hasText: documentState.legalFileName }).count()), "Deleted source document still appears in the case UI");

  await page.goto(`${WEB_URL}/app/evidence/${evidenceBundleId}`);
  await waitForPageReady(page);
  await page.getByRole("button", { name: "Download ZIP" }).waitFor({ timeout: 10_000 });
  await page.getByText("Document deleted").waitFor({ timeout: 10_000 });

  const evidencePayload = await readJson(
    await page.context().request.get(`${API_URL}/api/v1/evidence/${evidenceBundleId}`),
    "Evidence preview after source delete",
  );
  assert(
    evidencePayload.chainOfCustody.some((event) => event.eventType === "document.deleted"),
    "Evidence preview did not retain the document deletion custody event",
  );
  await takeShot(page, "document-deleted-evidence-retained.png");
}

async function main() {
  await fs.mkdir(ARTIFACT_DIR, { recursive: true });

  const runId = Date.now();
  const browser = await chromium.launch({ headless: HEADLESS });
  const context = await browser.newContext({ acceptDownloads: true });
  const page = await context.newPage();
  const consoleErrors = [];
  attachConsoleCollector(page, consoleErrors);

  try {
    const health = await context.request.get(`${API_URL}/health`);
    await ensureResponseOk(health, "API health check");
    const statusPayload = await readJson(await context.request.get(`${API_URL}/status`), "API status check");

    await loginWithTestAuth(page, OWNER_WALLET, "Playwright User");
    await page.goto(`${WEB_URL}/app/vault`);
    await waitForPageReady(page);
    const buildMeta = await verifyServedBuild(page);
    const shareState = await createVaultFileFlow(page, runId);
    await verifyRecipientShareFlow(browser, shareState, consoleErrors);
    await revokeShare(page, shareState);
    await deleteVaultFile(page, shareState);
    const documentState = await createCaseAndDocumentFlow(page, runId);
    const evidenceBundleId = await notarizeEvidenceFlow(page);
    const redactionDocumentId = await redactionFlow(page, getRedactionTimeoutMs(statusPayload));
    await deleteSourceDocumentFlow(page, documentState, evidenceBundleId, redactionDocumentId);

    assert(consoleErrors.length === 0, `Unexpected browser console errors: ${consoleErrors.join(" | ")}`);
    await fs.writeFile(
      path.join(ARTIFACT_DIR, "local-e2e-summary.json"),
      JSON.stringify(
        {
          webUrl: WEB_URL,
          apiUrl: API_URL,
          completedAt: new Date().toISOString(),
          runId,
          status: "passed",
          buildId: buildMeta.buildId,
          sourceHash: buildMeta.sourceHash,
        },
        null,
        2,
      ),
      "utf8",
    );
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch(async (error) => {
  await fs.mkdir(ARTIFACT_DIR, { recursive: true });
  await fs.writeFile(
    path.join(ARTIFACT_DIR, "local-e2e-summary.json"),
    JSON.stringify(
      {
        webUrl: WEB_URL,
        apiUrl: API_URL,
        completedAt: new Date().toISOString(),
        status: "failed",
        error: error instanceof Error ? error.message : String(error),
      },
      null,
      2,
    ),
    "utf8",
  );
  console.error(error);
  process.exitCode = 1;
});
