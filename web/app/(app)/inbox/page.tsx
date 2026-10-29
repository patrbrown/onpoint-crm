"use client";

import { Empty } from "@/components/ui";

export default function InboxPage() {
  return (
    <>
      <div className="page-head"><div><h1>Email inbox</h1>
        <p>Job requisitions, resumes and interview feedback found in your Outlook, waiting for your review.</p></div></div>
      <Empty title="Outlook isn’t connected yet">
        <p>This connects once your Microsoft 365 admin registers the app and sends the Application (client) ID and
          Directory (tenant) ID. Email is read only; nothing in Outlook is moved, flagged or changed.</p>
      </Empty>
    </>
  );
}
