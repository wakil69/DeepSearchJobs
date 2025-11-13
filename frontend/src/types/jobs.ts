export interface JobInfo {
  id: number;
  jobTitle: string;
  jobUrl: string;
  company: string;
  companyId?: number;
  locationCountry: string;
  locationRegion: string;
  salary?: string;
  contractType?: string;
  dateFetched: string;
  skillsRequired?: string[];
  status?: "applied" | "not_interested";
  emails?: string[];
}

export interface SetJobStatusPayload {
  jobId: number;
  status: "applied" | "not_interested";
}

export interface JobsResponse {
  jobs: JobInfo[];
  total: number;
  page: number;
  pageSize: number;
}

export type ContractType =  "full_time" | "part_time" | "internship" | "freelance" | "short_term" | "apprenticeship" | "graduate_program" | "remote"