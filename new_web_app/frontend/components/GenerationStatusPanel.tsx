
import React, { useEffect, useState } from 'react';
import { adminApi } from '../lib/api';

interface Job {
    id: number;
    status: string;
    topic: string;
    main_header: string | null;
    progress: number;
    total_items: number;
    generated_count: number;
    created_at: string;
    updated_at: string;
    error_message: string | null;
}

const GenerationStatusPanel: React.FC = () => {
    const [jobs, setJobs] = useState<Job[]>([]);
    const [loading, setLoading] = useState(true);

    const fetchJobs = async () => {
        try {
            const data = await adminApi.getGenerationJobs();
            setJobs(data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchJobs();
        const interval = setInterval(fetchJobs, 5000); // Refresh every 5s
        return () => clearInterval(interval);
    }, []);

    if (loading && jobs.length === 0) return <div className="text-sm text-gray-400 p-4">Loading status...</div>;

    const activeJobs = jobs.filter(j => ['pending', 'running'].includes(j.status));
    const recentJobs = jobs.filter(j => !['pending', 'running'].includes(j.status)).slice(0, 5);

    const StatusBadge = ({ status }: { status: string }) => {
        const colors: Record<string, string> = {
            pending: 'bg-yellow-500/20 text-yellow-400',
            running: 'bg-blue-500/20 text-blue-400 animate-pulse',
            completed: 'bg-green-500/20 text-green-400',
            failed: 'bg-red-500/20 text-red-400',
        };
        return (
            <span className={`text-xs px-2 py-0.5 rounded uppercase font-bold tracking-wider ${colors[status] || 'bg-gray-500/20 text-gray-400'}`}>
                {status}
            </span>
        );
    };

    const JobItem = ({ job }: { job: Job }) => (
        <div className="bg-[#1e1e1e] border border-white/5 rounded p-3 mb-2">
            <div className="flex justify-between items-start mb-1">
                <div className="flex-1 min-w-0 pr-2">
                    <h4 className="text-sm font-medium text-gray-200 truncate" title={job.topic}>
                        {job.topic}
                    </h4>
                    {job.main_header && (
                        <p className="text-xs text-blue-400 mt-0.5 truncate">{job.main_header}</p>
                    )}
                </div>
                <StatusBadge status={job.status} />
            </div>

            <div className="mt-2 flex items-center justify-between text-xs text-gray-400">
                <span>{new Date(job.created_at).toLocaleTimeString()}</span>
                <span>
                    {job.generated_count} / {job.total_items > 0 ? job.total_items : '?'} Q
                </span>
            </div>

            {job.status === 'running' && (
                <div className="mt-2 h-1 bg-gray-700 rounded-full overflow-hidden">
                    <div
                        className="h-full bg-blue-500 transition-all duration-500"
                        style={{ width: `${Math.min((job.generated_count / Math.max(job.total_items, 1)) * 100, 100)}%` }}
                    />
                </div>
            )}

            {job.error_message && (
                <div className="mt-2 text-xs text-red-400 bg-red-900/20 p-1.5 rounded border border-red-500/20 break-all">
                    {job.error_message.slice(0, 100)}...
                </div>
            )}
        </div>
    );

    return (
        <div className="mt-6 border-t border-white/10 pt-4">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-3 px-1">
                Generation Status
            </h3>

            {activeJobs.length > 0 && (
                <div className="mb-4">
                    <h4 className="text-xs text-blue-400 mb-2 font-medium flex items-center gap-2">
                        <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                        Active Jobs
                    </h4>
                    {activeJobs.map(job => <JobItem key={job.id} job={job} />)}
                </div>
            )}

            <div>
                <h4 className="text-xs text-gray-500 mb-2 font-medium">Recent History</h4>
                {recentJobs.length > 0 ? (
                    recentJobs.map(job => <JobItem key={job.id} job={job} />)
                ) : (
                    <p className="text-xs text-gray-600 italic px-1">No recent jobs</p>
                )}
            </div>
        </div>
    );
};

export default GenerationStatusPanel;
