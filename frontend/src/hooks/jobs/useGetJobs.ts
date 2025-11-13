import { useQuery } from "@tanstack/react-query";
import type { ContractType, JobsResponse } from "../../types/jobs";
import customRequest from "../../lib/axios";

export interface GetJobsParams {
  page?: number;
  pageSize?: number;
  country?: string;
  regions?: string[];
  contractType?: ContractType;
  companyId?: number;
  search?: string;
  status?: "applied" | "not_interested";
}

export default function useGetJobs(params: GetJobsParams) {
  const getJobs = async () => {
    try {
      const response = await customRequest.get<JobsResponse>("/jobs/", {
        params,
      });

      if (response.status !== 200) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }

      return response.data;
    } catch (err) {
      console.error(err);
      throw new Error("Server Error");
    }
  };

  const { data: jobsProposals, isFetching: isFetchingJobsProposals } = useQuery({
    queryKey: ["jobs", params],
    queryFn: getJobs,
    refetchOnMount: true,
    refetchOnWindowFocus: false,
    enabled: !params.status
  });

  return {
    jobsProposals,
    isFetchingJobsProposals,
  };
}
