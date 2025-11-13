import axios from "axios";

const customRequest = axios.create({
  baseURL: "http://localhost:4000",
  withCredentials: true,
});

export default customRequest;