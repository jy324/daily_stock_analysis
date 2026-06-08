import apiClient from './index';
import { toCamelCase } from './utils';

export type AShareIntelligenceCapability = {
  enabled: boolean;
  providerInstalled: boolean;
  reportEnabled: boolean;
  agentToolsEnabled: boolean;
  scoringEnabled: boolean;
};

export type RuntimeCapabilities = {
  ashareIntelligence: AShareIntelligenceCapability;
};

export const capabilitiesApi = {
  async getCapabilities(): Promise<RuntimeCapabilities> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/capabilities');
    return toCamelCase<RuntimeCapabilities>(response.data);
  },
};
