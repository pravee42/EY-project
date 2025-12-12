"use client";

import React, { useEffect, useState } from "react";
import { cn } from "../utils"; // Adjusted path to valid utils
import { MotionConfig, motion } from "framer-motion";
import { CheckCircle, XCircle, AlertCircle, RefreshCw, BarChart, Activity, FileText } from "lucide-react";

interface Tender {
    _id?: string;
    title: string;
    summary: string;
    approval_status?: string;
    sales_processed?: boolean;
    technical_processed?: boolean;
    pricing_processed?: boolean;
    master_processed?: boolean;
    scraped_at?: string;
    final_report_pdf_path?: string;
    category?: string;
    total_tender_price?: number;
}

export default function Dashboard() {
    const [tenders, setTenders] = useState<Tender[]>([]);
    const [pendingTenders, setPendingTenders] = useState<Tender[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshKey, setRefreshKey] = useState(0);

    const API_BASE = "http://127.0.0.1:8000";

    const fetchData = async () => {
        try {
            // Fetch All Tenders
            const allRes = await fetch(`${API_BASE}/tenders`);
            const allData = await allRes.json();
            setTenders(allData);

            // Fetch Pending
            const pendingRes = await fetch(`${API_BASE}/api/tenders/pending-approval`);
            const pendingData = await pendingRes.json();
            setPendingTenders(pendingData);

        } catch (err) {
            console.error("Failed to fetch data:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 5000); // Poll every 5s
        return () => clearInterval(interval);
    }, [refreshKey]);

    const handleApprove = async (id: string) => {
        try {
            await fetch(`${API_BASE}/api/tenders/${id}/approve`, { method: "POST" });
            setRefreshKey((k) => k + 1);
        } catch (e) {
            console.error(e);
        }
    };

    const handleReject = async (id: string) => {
        const reason = prompt("Enter rejection reason:");
        if (!reason) return;
        try {
            await fetch(`${API_BASE}/api/tenders/${id}/reject`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ reason }),
            });
            setRefreshKey((k) => k + 1);
        } catch (e) {
            console.error(e);
        }
    };

    // Stats
    const total = tenders.length;
    const approved = tenders.filter(t => t.approval_status === "APPROVED").length;
    const rejected = tenders.filter(t => t.approval_status === "REJECTED").length;
    const pending = pendingTenders.length;

    return (
        <div className="min-h-screen bg-background p-8 font-sans">
            <header className="mb-8 flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-white mb-1">
                        RFP Yukti <span className="text-blue-500">Mission Control</span>
                    </h1>
                    <p className="text-muted-foreground">Real-time Tender Intelligence System</p>
                </div>
                <div className="flex gap-4">
                    <div className="bg-card border border-border px-4 py-2 rounded-lg flex items-center gap-2">
                        <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                        <span className="text-sm font-medium">System Online</span>
                    </div>
                </div>
            </header>

            {/* Stats Row */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
                <StatCard title="Total Tenders" value={total} icon={<FileText className="h-4 w-4 text-blue-400" />} />
                <StatCard title="Pending Approval" value={pending} icon={<AlertCircle className="h-4 w-4 text-yellow-400" />} highlight={pending > 0} />
                <StatCard title="Approved" value={approved} icon={<CheckCircle className="h-4 w-4 text-green-400" />} />
                <StatCard title="Rejected" value={rejected} icon={<XCircle className="h-4 w-4 text-red-400" />} />
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 h-[calc(100vh-250px)]">

                {/* Left Col: Approval Queue */}
                <div className="lg:col-span-1 flex flex-col gap-4 h-full">
                    <div className="flex items-center justify-between">
                        <h2 className="text-xl font-semibold text-yellow-500 flex items-center gap-2">
                            <Activity className="h-5 w-5" />
                            Pending Approval
                        </h2>
                        <span className="text-xs bg-yellow-500/10 text-yellow-500 px-2 py-1 rounded-full">{pending} items</span>
                    </div>

                    <div className="flex-1 overflow-y-auto pr-2 space-y-4">
                        {pendingTenders.length === 0 ? (
                            <div className="text-center p-8 border border-dashed border-border rounded-xl text-muted-foreground">
                                No tenders waiting for approval.
                            </div>
                        ) : (
                            pendingTenders.map((t) => (
                                <Card key={t._id} className="p-4 border-yellow-500/30 bg-yellow-950/10">
                                    <h3 className="font-semibold text-lg text-yellow-100 truncate">{t.title}</h3>
                                    <p className="text-xs text-yellow-200/50 mb-4">{t.category || "Uncategorized"}</p>

                                    <div className="grid grid-cols-2 gap-2 text-sm mb-4">
                                        <div className="bg-background/50 p-2 rounded">
                                            <div className="text-muted-foreground text-xs">Value</div>
                                            <div className="font-mono">{t.total_tender_price ? `₹${t.total_tender_price.toLocaleString()}` : 'N/A'}</div>
                                        </div>
                                        <div className="bg-background/50 p-2 rounded">
                                            <div className="text-muted-foreground text-xs">Due</div>
                                            <div className="font-mono">Today</div>
                                        </div>
                                    </div>

                                    <div className="flex gap-2">
                                        <button
                                            onClick={() => t._id && handleApprove(t._id)}
                                            className="flex-1 bg-green-600 hover:bg-green-700 text-white text-xs font-bold py-2 rounded transition-colors"
                                        >
                                            APPROVE
                                        </button>
                                        <button
                                            onClick={() => t._id && handleReject(t._id)}
                                            className="flex-1 bg-red-900/50 hover:bg-red-900 text-red-200 text-xs font-bold py-2 rounded transition-colors"
                                        >
                                            REJECT
                                        </button>
                                    </div>
                                </Card>
                            ))
                        )}
                    </div>
                </div>

                {/* Right Col: Operations Log / Master List */}
                <div className="lg:col-span-2 flex flex-col gap-4 h-full">
                    <h2 className="text-xl font-semibold text-blue-400 flex items-center gap-2">
                        <BarChart className="h-5 w-5" />
                        Pipeline Activity
                    </h2>

                    <div className="flex-1 bg-card border border-border rounded-xl overflow-hidden flex flex-col">
                        <div className="grid grid-cols-12 gap-4 p-4 border-b border-border bg-muted/50 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                            <div className="col-span-5">Tender</div>
                            <div className="col-span-2">Stage</div>
                            <div className="col-span-2">Value</div>
                            <div className="col-span-3 text-right">Action</div>
                        </div>
                        <div className="overflow-y-auto flex-1 p-2">
                            {tenders.map((t) => (
                                <div key={t._id || t.title} className="grid grid-cols-12 gap-4 p-3 hover:bg-white/5 rounded-lg items-center transition-colors border-b border-border/50 last:border-0">
                                    <div className="col-span-5">
                                        <div className="font-medium text-sm text-white truncate" title={t.title}>{t.title}</div>
                                        <div className="text-xs text-muted-foreground">{t.category}</div>
                                    </div>
                                    <div className="col-span-2">
                                        <StageBadge tender={t} />
                                    </div>
                                    <div className="col-span-2">
                                        <div className="text-sm font-mono text-emerald-400">
                                            {t.total_tender_price ? `₹${(t.total_tender_price / 100000).toFixed(1)}L` : '-'}
                                        </div>
                                    </div>
                                    <div className="col-span-3 text-right">
                                        {t.final_report_pdf_path ? (
                                            <a
                                                href={`${API_BASE}/api/tenders/${t._id}/report/pdf`}
                                                target="_blank"
                                                className="inline-flex items-center gap-1 text-xs bg-blue-600 hover:bg-blue-500 text-white px-2 py-1 rounded"
                                            >
                                                <FileText className="h-3 w-3" /> Report
                                            </a>
                                        ) : (
                                            <span className="text-xs text-muted-foreground">Processing...</span>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

            </div>
        </div>
    );
}

function StatCard({ title, value, icon, highlight }: any) {
    return (
        <div className={cn("p-4 rounded-xl border bg-card flex items-center justify-between", highlight ? "border-yellow-500/50 bg-yellow-500/10" : "border-border")}>
            <div>
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{title}</p>
                <div className="text-2xl font-bold text-white mt-1">{value}</div>
            </div>
            <div className={cn("p-3 rounded-full bg-white/5", highlight && "bg-yellow-500/20")}>
                {icon}
            </div>
        </div>
    )
}

function Card({ className, children }: { className?: string, children: React.ReactNode }) {
    return <div className={cn("rounded-xl border bg-card", className)}>{children}</div>
}

function StageBadge({ tender }: { tender: Tender }) {
    if (tender.master_processed) return <Badge color="green">Complete</Badge>
    if (tender.approval_status === 'REJECTED') return <Badge color="red">Rejected</Badge>
    if (tender.approval_status === 'APPROVED') return <Badge color="blue">Processing</Badge>
    if (tender.pricing_processed) return <Badge color="yellow">Needs Approval</Badge>
    if (tender.technical_processed) return <Badge color="purple">Pricing</Badge>
    return <Badge color="gray">Scraping</Badge>
}

function Badge({ children, color }: { children: React.ReactNode, color: string }) {
    const colors: Record<string, string> = {
        green: "bg-green-500/20 text-green-400 border-green-500/30",
        red: "bg-red-500/20 text-red-400 border-red-500/30",
        blue: "bg-blue-500/20 text-blue-400 border-blue-500/30",
        yellow: "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
        purple: "bg-purple-500/20 text-purple-400 border-purple-500/30",
        gray: "bg-gray-500/20 text-gray-400 border-gray-500/30",
    }
    return (
        <span className={cn("px-2 py-0.5 rounded text-[10px] font-bold uppercase border", colors[color] || colors.gray)}>
            {children}
        </span>
    )
}
