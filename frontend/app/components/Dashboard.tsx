"use client";

import React, { useEffect, useState, useRef } from "react";
import { cn } from "../utils";
import { motion, AnimatePresence } from "framer-motion";
import {
    CheckCircle, XCircle, AlertCircle, RefreshCw, BarChart, Activity,
    FileText, Search, MessageSquare, Mic, Send, X, Filter, ChevronRight,
    LayoutDashboard, Settings, List
} from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";

const API_BASE = "http://127.0.0.1:8000";

// --- Types ---
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
    competitor_analysis?: {
        competitors: string[];
        win_probability: number;
        risks: string[];
        rationale: string;
    };
}

interface CeleryTask {
    task_id: string;
    status: string;         // RUNNING, COMPLETED, FAILED
    current_stage: string;  // SCRAPING, sales_agent, etc.
    updated_at: string;
    details?: any;
}

// --- Dashboard Component ---
export default function Dashboard() {
    const [tenders, setTenders] = useState<Tender[]>([]);
    const [tasks, setTasks] = useState<CeleryTask[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshKey, setRefreshKey] = useState(0);

    // Filters
    const [search, setSearch] = useState("");
    const [statusFilter, setStatusFilter] = useState("ALL"); // ALL, PENDING, APPROVED, REJECTED

    const fetchData = async () => {
        try {
            const [tendersRes, tasksRes] = await Promise.all([
                fetch(`${API_BASE}/tenders`),
                fetch(`${API_BASE}/api/tasks`)
            ]);

            const tendersData = await tendersRes.json();
            const tasksData = await tasksRes.json();

            setTenders(tendersData);
            setTasks(tasksData);
        } catch (err) {
            console.error("Failed to fetch data:", err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchData();
        const interval = setInterval(fetchData, 3000);
        return () => clearInterval(interval);
    }, [refreshKey]);

    // Derived State
    const filteredTenders = tenders.filter(t => {
        const matchesSearch = t.title.toLowerCase().includes(search.toLowerCase()) ||
            t.category?.toLowerCase().includes(search.toLowerCase());

        let matchesStatus = true;
        if (statusFilter === "PENDING") matchesStatus = !t.master_processed && t.approval_status !== "REJECTED";
        if (statusFilter === "APPROVED") matchesStatus = t.approval_status === "APPROVED";
        if (statusFilter === "REJECTED") matchesStatus = t.approval_status === "REJECTED";

        return matchesSearch && matchesStatus;
    });

    return (
        <div className="flex h-screen bg-gray-50 font-sans text-slate-900">

            {/* Sidebar Navigation */}
            <Sidebar tasks={tasks} />

            {/* Main Content */}
            <div className="flex-1 flex flex-col overflow-hidden">

                {/* Top Header */}
                <header className="h-16 bg-white border-b border-gray-200 flex items-center justify-between px-8 shadow-sm z-10">
                    <div className="flex items-center gap-4">
                        <Search className="h-5 w-5 text-gray-400" />
                        <input
                            type="text"
                            placeholder="Search tenders..."
                            className="bg-transparent border-none outline-none text-sm w-64 text-slate-700 placeholder-gray-400"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                        />
                    </div>

                    <div className="flex items-center gap-4">
                        <FilterTabs current={statusFilter} onChange={setStatusFilter} />
                        <div className="h-8 w-8 bg-purple-100 rounded-full flex items-center justify-center text-purple-700 font-bold text-xs ring-2 ring-purple-100">
                            PK
                        </div>
                    </div>
                </header>

                {/* Scrollable Canvas */}
                <main className="flex-1 overflow-y-auto p-8">
                    <div className="max-w-7xl mx-auto">

                        <div className="flex items-center justify-between mb-8">
                            <div>
                                <h1 className="text-2xl font-bold text-slate-900">Procurement Overview</h1>
                                <p className="text-slate-500 text-sm">Managing {tenders.length} active opportunities</p>
                            </div>
                            <button
                                onClick={() => fetch(`${API_BASE}/api/celery/start-process`, { method: "POST" })}
                                className="bg-primary hover:bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 shadow-lg shadow-indigo-200 transition-all active:scale-95"
                            >
                                <RefreshCw className="h-4 w-4" />
                                Run Pipeline
                            </button>
                        </div>

                        <div className="grid grid-cols-1 gap-6">
                            {filteredTenders.map((t) => (
                                <TenderCard key={t._id} tender={t} onRefresh={() => setRefreshKey(k => k + 1)} />
                            ))}
                            {filteredTenders.length === 0 && (
                                <div className="text-center py-20 text-gray-400 bg-white rounded-xl border border-dashed">
                                    No tenders match your filters.
                                </div>
                            )}
                        </div>

                    </div>
                </main>
            </div>

        </div>
    );
}

// --- Sub Components ---

function Sidebar({ tasks }: { tasks: CeleryTask[] }) {
    return (
        <div className="w-80 bg-white border-r border-gray-200 flex flex-col h-full shadow-[4px_0_24px_rgba(0,0,0,0.02)] z-20">
            <div className="p-6 border-b border-gray-100">
                <h1 className="font-bold text-xl flex items-center gap-2 text-indigo-600">
                    <LayoutDashboard className="h-6 w-6" />
                    RFP Yukti
                </h1>
            </div>

            <div className="p-4 flex-1 overflow-y-auto">
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-4 px-2">Live Tasks</h3>
                <div className="space-y-3">
                    {tasks.length === 0 ? (
                        <div className="px-2 text-sm text-gray-400 italic">No active tasks.</div>
                    ) : (
                        tasks.slice(0, 10).map((task) => (
                            <TaskItem key={task.task_id} task={task} />
                        ))
                    )}
                </div>
            </div>

            <div className="p-4 border-t border-gray-100 bg-gray-50/50">
                <div className="flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-gray-100 cursor-pointer text-gray-600 text-sm transition-colors">
                    <Settings className="h-4 w-4" />
                    <span>Settings</span>
                </div>
            </div>
        </div>
    )
}

function TaskItem({ task }: { task: CeleryTask }) {
    const isRunning = task.status === "RUNNING";
    const isFailed = task.status === "ERROR" || task.status === "FAILED";

    return (
        <div className="bg-white border boundary border-gray-100 rounded-lg p-3 shadow-sm relative overflow-hidden group">
            <div className="flex justify-between items-start mb-2">
                <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded",
                    isRunning ? "bg-blue-100 text-blue-700" :
                        isFailed ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700")}>
                    {task.status}
                </span>
                <span className="text-[10px] text-gray-400">{new Date(task.updated_at).toLocaleTimeString()}</span>
            </div>
            <div className="text-xs font-medium text-slate-700 mb-1 flex items-center gap-1">
                {task.current_stage}
                {isRunning && <RefreshCw className="h-3 w-3 animate-spin text-blue-500" />}
            </div>
            {isRunning && (
                <div className="h-1 w-full bg-gray-100 rounded-full mt-2 overflow-hidden">
                    <motion.div
                        initial={{ x: "-100%" }}
                        animate={{ x: "100%" }}
                        transition={{ repeat: Infinity, duration: 1.5, ease: "linear" }}
                        className="h-full w-full bg-blue-500 rounded-full origin-left"
                    />
                </div>
            )}
        </div>
    )
}

function FilterTabs({ current, onChange }: any) {
    const tabs = ["ALL", "PENDING", "APPROVED", "REJECTED"];
    return (
        <div className="flex bg-gray-100 p-1 rounded-lg">
            {tabs.map(tab => (
                <button
                    key={tab}
                    onClick={() => onChange(tab)}
                    className={cn(
                        "text-xs font-bold px-3 py-1.5 rounded-md transition-all",
                        current === tab ? "bg-white text-indigo-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
                    )}
                >
                    {tab}
                </button>
            ))}
        </div>
    )
}

function TenderCard({ tender, onRefresh }: { tender: Tender, onRefresh: () => void }) {
    const isApproved = tender.approval_status === "APPROVED";
    const isRejected = tender.approval_status === "REJECTED";
    const isPending = !isApproved && !isRejected && tender.pricing_processed; // Assuming pending if pricing done but not approved

    // Competitor Intel State
    const [analyzing, setAnalyzing] = useState(false);

    const runAnalysis = async () => {
        setAnalyzing(true);
        try {
            await fetch(`${API_BASE}/api/tenders/${tender._id}/analyze-competitors`, { method: "POST" });
            onRefresh();
        } catch (e) {
            console.error(e);
        } finally {
            setAnalyzing(false);
        }
    };

    return (
        <motion.div layout initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="bg-white rounded-xl border border-gray-100 shadow-sm hover:shadow-md transition-all p-5">
            <div className="flex justify-between items-start">
                <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                        <span className="text-[10px] font-bold tracking-wider text-gray-400 uppercase">{tender.category || "General"}</span>
                        {isApproved && <span className="flex items-center gap-1 text-[10px] font-bold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full"><CheckCircle className="h-3 w-3" /> Approved</span>}
                        {isRejected && <span className="flex items-center gap-1 text-[10px] font-bold text-rose-600 bg-rose-50 px-2 py-0.5 rounded-full"><XCircle className="h-3 w-3" /> Rejected</span>}
                        {isPending && <span className="flex items-center gap-1 text-[10px] font-bold text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full"><AlertCircle className="h-3 w-3" /> Action Required</span>}
                    </div>
                    <h3 className="text-lg font-semibold text-slate-800 mb-1 leading-tight">{tender.title}</h3>
                    <p className="text-sm text-slate-500 line-clamp-2 mb-4 max-w-2xl">{tender.summary}</p>

                    {/* Stages Stepper */}
                    <div className="flex items-center gap-1 mb-4">
                        <StageDot label="Sales" active={!!tender.sales_processed} />
                        <div className="w-4 h-[1px] bg-gray-200" />
                        <StageDot label="Technical" active={!!tender.technical_processed} />
                        <div className="w-4 h-[1px] bg-gray-200" />
                        <StageDot label="Pricing" active={!!tender.pricing_processed} />
                        <div className="w-4 h-[1px] bg-gray-200" />
                        <StageDot label="Master" active={!!tender.master_processed} final />
                    </div>

                    {/* Competitor Analysis Section */}
                    {tender.competitor_analysis ? (
                        <div className="mb-4 bg-slate-50 p-3 rounded-lg border border-slate-100 text-xs">
                            <div className="flex items-center justify-between mb-2">
                                <span className="font-bold text-slate-700 flex items-center gap-1">
                                    <Activity className="h-3 w-3 text-indigo-500" /> Market Intel
                                </span>
                                <span className={cn("px-2 py-0.5 rounded-full font-bold",
                                    tender.competitor_analysis.win_probability > 70 ? "bg-green-100 text-green-700" :
                                        tender.competitor_analysis.win_probability > 40 ? "bg-yellow-100 text-yellow-700" : "bg-red-100 text-red-700"
                                )}>
                                    {tender.competitor_analysis.win_probability}% Win Prob.
                                </span>
                            </div>
                            <div className="grid grid-cols-2 gap-4">
                                <div>
                                    <span className="text-slate-400 uppercase tracking-wider text-[10px]">Likely Competitors</span>
                                    <div className="text-slate-700 font-medium">{tender.competitor_analysis.competitors.join(", ")}</div>
                                </div>
                                <div>
                                    <span className="text-slate-400 uppercase tracking-wider text-[10px]">Key Risks</span>
                                    <div className="text-slate-700 font-medium truncate" title={tender.competitor_analysis.risks.join(", ")}>
                                        {tender.competitor_analysis.risks[0]}...
                                    </div>
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="mb-4">
                            <button
                                onClick={runAnalysis}
                                disabled={analyzing}
                                className="text-xs text-indigo-600 font-medium flex items-center gap-1 hover:underline disabled:opacity-50"
                            >
                                {analyzing ? <RefreshCw className="h-3 w-3 animate-spin" /> : <BarChart className="h-3 w-3" />}
                                {analyzing ? "Analyzing Competitors..." : "Generate Competitor Intel"}
                            </button>
                        </div>
                    )}
                </div>

                <div className="flex flex-col items-end gap-3 pl-4 border-l border-gray-50 min-w-[140px]">
                    <div className="text-right">
                        <div className="text-[10px] text-gray-400 uppercase">Est. Value</div>
                        <div className="text-lg font-mono font-bold text-slate-700">
                            {tender.total_tender_price ? `₹${(tender.total_tender_price / 100000).toFixed(1)}L` : '--'}
                        </div>
                    </div>

                    <div className="flex gap-2">
                        <ChatBubble tenderId={tender._id} title={tender.title} />
                        {tender.final_report_pdf_path && (
                            <a
                                href={`${API_BASE}/api/tenders/${tender._id}/report/pdf`}
                                target="_blank"
                                className="p-2 rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-600 transition-colors"
                                title="Download Report"
                            >
                                <FileText className="h-4 w-4" />
                            </a>
                        )}
                    </div>
                </div>
            </div>

            {/* Actions Footer */}
            {isPending && (
                <div className="mt-4 pt-4 border-t border-gray-50 flex items-center justify-between bg-amber-50/30 -mx-5 -mb-5 px-5 py-3">
                    <span className="text-xs font-medium text-amber-800 flex items-center gap-2">
                        <AlertCircle className="h-4 w-4" />
                        Review required
                    </span>
                    <div className="flex gap-3">
                        <RejectionDialog tenderId={tender._id} onRefresh={onRefresh} />
                        <button
                            onClick={async () => {
                                await fetch(`${API_BASE}/api/tenders/${tender._id}/approve`, { method: "POST" });
                                onRefresh();
                            }}
                            className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold px-4 py-2 rounded-lg shadow-sm transition-all"
                        >
                            Approve
                        </button>
                    </div>
                </div>
            )}
        </motion.div>
    )
}

function StageDot({ label, active, final }: any) {
    return (
        <div className="flex flex-col items-center gap-1">
            <div className={cn("h-2.5 w-2.5 rounded-full transition-colors", active ? (final ? "bg-indigo-600" : "bg-blue-500") : "bg-gray-200")} />
            {/* <span className="text-[9px] text-gray-400 uppercase">{label}</span> */}
        </div>
    )
}

// --- Chat Bubble Component ---
function ChatBubble({ tenderId, title }: { tenderId?: string, title: string }) {
    const [isOpen, setIsOpen] = useState(false);
    const [messages, setMessages] = useState<{ role: 'user' | 'ai', text: string }[]>([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const bottomRef = useRef<HTMLDivElement>(null);
    const [listening, setListening] = useState(false);

    const handleSend = async () => {
        if (!input.trim() || !tenderId) return;

        const userMsg = input;
        setInput("");
        setMessages(prev => [...prev, { role: 'user', text: userMsg }]);
        setLoading(true);

        try {
            const res = await fetch(`${API_BASE}/api/tenders/${tenderId}/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: userMsg })
            });
            const data = await res.json();
            setMessages(prev => [...prev, { role: 'ai', text: data.answer }]);
        } catch (e) {
            setMessages(prev => [...prev, { role: 'ai', text: "Error connecting to AI." }]);
        } finally {
            setLoading(false);
        }
    };

    // Voice Handler
    const startListening = () => {
        if (!('webkitSpeechRecognition' in window)) {
            alert("Voice input not supported in this browser.");
            return;
        }

        const recognition = new (window as any).webkitSpeechRecognition();
        recognition.lang = 'en-US';
        recognition.start();
        setListening(true);

        recognition.onresult = (event: any) => {
            const transcript = event.results[0][0].transcript;
            setInput(transcript);
            setListening(false);
        };

        recognition.onerror = () => setListening(false);
        recognition.onend = () => setListening(false);
    };

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages]);

    return (
        <Popover.Root open={isOpen} onOpenChange={setIsOpen}>
            <Popover.Trigger asChild>
                <button className="p-2 rounded-lg bg-indigo-50 hover:bg-indigo-100 text-indigo-600 transition-colors relative">
                    <MessageSquare className="h-4 w-4" />
                </button>
            </Popover.Trigger>
            <Popover.Portal>
                <Popover.Content className="w-80 h-96 bg-white rounded-xl shadow-xl border border-gray-200 flex flex-col overflow-hidden z-50 animate-in fade-in zoom-in-95 duration-200 mr-4" sideOffset={5} align="end">
                    <div className="p-3 border-b border-gray-100 bg-indigo-50/50 flex justify-between items-center">
                        <span className="text-xs font-bold text-indigo-900 flex items-center gap-2">
                            <span className="h-2 w-2 rounded-full bg-indigo-500 animate-pulse" />
                            AI Procurement Assistant
                        </span>
                        <Popover.Close className="text-gray-400 hover:text-gray-600"><X className="h-4 w-4" /></Popover.Close>
                    </div>

                    <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-slate-50/30">
                        {messages.length === 0 && (
                            <div className="text-center text-xs text-gray-400 mt-10">
                                Ask me anything about <br />"{title.slice(0, 20)}..."
                            </div>
                        )}
                        {messages.map((m, i) => (
                            <div key={i} className={cn("text-xs p-2 rounded-lg max-w-[85%]", m.role === 'user' ? "bg-indigo-600 text-white ml-auto" : "bg-white border border-gray-200 text-slate-700 mr-auto")}>
                                {m.text}
                            </div>
                        ))}
                        {loading && (
                            <div className="bg-white border border-gray-200 p-2 rounded-lg mr-auto">
                                <span className="flex gap-1">
                                    <span className="h-1.5 w-1.5 bg-gray-400 rounded-full animate-bounce" />
                                    <span className="h-1.5 w-1.5 bg-gray-400 rounded-full animate-bounce delay-75" />
                                    <span className="h-1.5 w-1.5 bg-gray-400 rounded-full animate-bounce delay-150" />
                                </span>
                            </div>
                        )}
                        <div ref={bottomRef} />
                    </div>

                    <div className="p-3 border-t border-gray-100 bg-white flex gap-2">
                        <button
                            onClick={startListening}
                            className={cn("text-indigo-600 p-1 rounded hover:bg-indigo-50", listening && "bg-red-50 text-red-600 animate-pulse")}
                        >
                            <Mic className="h-4 w-4" />
                        </button>
                        <input
                            className="flex-1 text-xs outline-none text-slate-700"
                            placeholder={listening ? "Listening..." : "Type a question..."}
                            value={input}
                            onChange={e => setInput(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && handleSend()}
                        />
                        <button onClick={handleSend} disabled={loading} className="text-indigo-600 disabled:opacity-50">
                            <Send className="h-4 w-4" />
                        </button>
                    </div>
                </Popover.Content>
            </Popover.Portal>
        </Popover.Root>
    )
}

// --- Rejection Dialog Component ---
function RejectionDialog({ tenderId, onRefresh }: { tenderId?: string, onRefresh: () => void }) {
    const [reason, setReason] = useState("");
    const [open, setOpen] = useState(false);

    const handleReject = async () => {
        if (!tenderId) return;
        await fetch(`${API_BASE}/api/tenders/${tenderId}/reject`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason }),
        });
        setOpen(false);
        onRefresh();
    };

    return (
        <Dialog.Root open={open} onOpenChange={setOpen}>
            <Dialog.Trigger asChild>
                <button className="bg-white border border-gray-200 text-slate-600 hover:bg-gray-50 text-xs font-bold px-4 py-2 rounded-lg transition-all">
                    Reject
                </button>
            </Dialog.Trigger>
            <Dialog.Portal>
                <Dialog.Overlay className="fixed inset-0 bg-black/30 backdrop-blur-sm z-50 animate-in fade-in" />
                <Dialog.Content className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-xl shadow-2xl p-6 w-96 z-50 animate-in zoom-in-95">
                    <Dialog.Title className="text-lg font-bold text-slate-900 mb-2">Reject Tender</Dialog.Title>
                    <Dialog.Description className="text-sm text-slate-500 mb-4">
                        Please provide a reason for rejecting this tender. This will be logged for analytics.
                    </Dialog.Description>

                    <textarea
                        className="w-full border border-gray-200 rounded-lg p-3 text-sm focus:ring-2 focus:ring-rose-500 outline-none min-h-[100px]"
                        placeholder="e.g. Budget too high..."
                        value={reason}
                        onChange={e => setReason(e.target.value)}
                    />

                    <div className="flex justify-end gap-2 mt-4">
                        <Dialog.Close asChild>
                            <button className="px-4 py-2 text-sm text-slate-500 hover:bg-gray-100 rounded-lg">Cancel</button>
                        </Dialog.Close>
                        <button
                            onClick={handleReject}
                            disabled={!reason.trim()}
                            className="px-4 py-2 text-sm bg-rose-600 hover:bg-rose-700 text-white rounded-lg disabled:opacity-50 font-medium"
                        >
                            Confirm Reject
                        </button>
                    </div>
                </Dialog.Content>
            </Dialog.Portal>
        </Dialog.Root>
    )
}
