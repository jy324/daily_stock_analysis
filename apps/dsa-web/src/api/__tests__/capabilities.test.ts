import { describe, expect, it, vi } from 'vitest';
import apiClient from '../index';
import { capabilitiesApi } from '../capabilities';

vi.mock('../index', () => ({
  default: {
    get: vi.fn(),
  },
}));

describe('capabilitiesApi', () => {
  it('reads runtime capabilities from /api/v1/capabilities', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: {
        ashare_intelligence: {
          enabled: true,
          provider_installed: true,
          report_enabled: false,
          agent_tools_enabled: true,
          scoring_enabled: false,
        },
      },
    });

    const result = await capabilitiesApi.getCapabilities();

    expect(apiClient.get).toHaveBeenCalledWith('/api/v1/capabilities');
    expect(result.ashareIntelligence.agentToolsEnabled).toBe(true);
    expect(result.ashareIntelligence.providerInstalled).toBe(true);
  });
});
