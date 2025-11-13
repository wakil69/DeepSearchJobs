import { useQuery } from "@tanstack/react-query";
import type { ContractType, JobsResponse } from "../../types/jobs";
import customRequest from "../../lib/axios";

export interface GetJobsAppliedOrNotInterestedParams {
  page?: number;
  pageSize?: number;
  country?: string;
  regions?: string[];
  contract_type?: ContractType;
  search?: string;
  status?: "applied" | "not_interested";
}

export default function useGetJobsAppliedOrNotInterested(
  params: GetJobsAppliedOrNotInterestedParams
) {
  const getJobsAppliedOrNotInterested = async () => {
    try {
      const response = await customRequest.get<JobsResponse>(
        "/jobs/applied-or-not-interested",
        { params }
      );

      if (response.status !== 200) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }

      return response.data;
    } catch (err) {
      console.error(err);
      throw new Error("Server Error");
    }
  };

  const {
    data: jobsAppliedOrNotInterested,
    isFetching: isFetchingJobsAppliedOrNotInterested,
  } = useQuery({
    queryKey: ["jobs-applied-or-not-interested", params],
    queryFn: getJobsAppliedOrNotInterested,
    enabled: !!params.status,
    refetchOnMount: true,
    refetchOnWindowFocus: false,
  });

  return {
    jobsAppliedOrNotInterested,
    isFetchingJobsAppliedOrNotInterested,
  };
}
