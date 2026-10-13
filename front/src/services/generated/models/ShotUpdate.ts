/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ShotStatus } from './ShotStatus';
export type ShotUpdate = {
    chapter_id?: (string | null);
    index?: (number | null);
    title?: (string | null);
    thumbnail?: (string | null);
    status?: (ShotStatus | null);
    skip_extraction?: (boolean | null);
    script_excerpt?: (string | null);
    generated_video_file_id?: (string | null);
    generated_audio_file_id?: (string | null);
};

