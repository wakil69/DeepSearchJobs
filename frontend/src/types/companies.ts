export interface CompanyInfo {
  id: number;
  name: string;
  website?: string;
  emails?: string[];
  internalJobListingPages?: string[];
  externalJobListingPages?: string[];
  lastCheckedDate?: string;
  status?: "idle" | "queued" | "in_progress" | "done" | "error";
  numberJobs?: number;
}

export interface CompaniesResponse {
  companies: CompanyInfo[];
  total: number;
  page: number;
  pageSize: number;
}

export interface Company {
  id: number;
  name: string;
}

export type AllCompaniesResponse = Company[];