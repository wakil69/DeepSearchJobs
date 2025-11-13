import { useQuery } from "@tanstack/react-query";
import customRequest from "../../lib/axios";

export interface CompanyJobStatus {
  id: number;
  status: string;
}

export interface StatusGroup {
  jobs: CompanyJobStatus[];
  total: number;
}

export interface StatusResponse {
  analyse: StatusGroup;
  check: StatusGroup;
  totalAll: number;
}

export default function useGetStatusProcessCompanies() {
  const fetchStatus = async (): Promise<StatusResponse> => {
    try {
      const response = await customRequest.get<StatusResponse>("/status");

      if (response.status !== 200) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }

      return response.data;
    } catch (err: any) {
      console.error("Error fetching company job statuses:", err);
      throw new Error(
        err.response?.data?.message || "Failed to fetch job statuses."
      );
    }
  };

  const {
    data: statusData,
    isLoading,
    isFetching,
    isError,
    refetch,
  } = useQuery<StatusResponse>({
    queryKey: ["companies-status"],
    queryFn: fetchStatus,
    // refetchInterval: 15_000, 
    refetchOnWindowFocus: false,
  });

  return {
    statusData,
    isLoading,
    isFetching,
    isError,
    refetch,
  };
}
