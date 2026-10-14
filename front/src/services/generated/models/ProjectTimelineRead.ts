/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { TimelineClipRead } from './TimelineClipRead';
import type { TimelineStatsRead } from './TimelineStatsRead';
export type ProjectTimelineRead = {
    project_id: string;
    project_name: string;
    video_ratio?: (string | null);
    clips?: Array<TimelineClipRead>;
    stats: TimelineStatsRead;
};

