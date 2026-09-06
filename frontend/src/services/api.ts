export type ApiError = { error: { code: string; message: string; details?: unknown } };
export async function getHealth(baseUrl = "/api/v1"): Promise<{ status: string; database: string }> {
  const response = await fetch(`${baseUrl}/health/`);
  if (!response.ok) throw new Error((await response.json() as ApiError).error?.message ?? "API request failed");
  return response.json() as Promise<{ status: string; database: string }>;
}
