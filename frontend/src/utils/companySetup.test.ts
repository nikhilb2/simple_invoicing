import { describe, expect, test } from 'vitest';
import type { CompanyProfile } from '../types/api';
import { isCompanyConfigured, isGstinRequired } from './companySetup';

describe('isGstinRequired', () => {
  test('no company yet', () => {
    expect(isGstinRequired(null)).toBe(true);
  });

  test('a blank or half-finished company', () => {
    expect(isGstinRequired({ name: '', address: '', gst: '' } as CompanyProfile)).toBe(true);
    expect(isGstinRequired({ name: 'Rao Traders', address: ' ', gst: '' } as CompanyProfile)).toBe(true);
  });

  test('a company that already has one cannot blank it', () => {
    expect(isGstinRequired({ name: 'Rao Traders', address: '1 MG Road', gst: '27ABCDE1234F1Z0' } as CompanyProfile)).toBe(true);
  });

  test('a company set up without one can keep saving', () => {
    expect(isGstinRequired({ name: 'Rao Traders', address: '1 MG Road', gst: '' } as CompanyProfile)).toBe(false);
  });
});

describe('isCompanyConfigured — falsey or incomplete profiles are not configured', () => {
  test('null profile', () => {
    expect(isCompanyConfigured(null)).toBe(false);
  });

  test('undefined profile', () => {
    expect(isCompanyConfigured(undefined)).toBe(false);
  });

  test('empty company name', () => {
    const profile = { name: '' } as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(false);
  });

  test('whitespace-only company name', () => {
    const profile = { name: '   ' } as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(false);
  });

  test('profile object without name property', () => {
    const profile = {} as unknown as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(false);
  });
});

describe('isCompanyConfigured — valid profiles are configured', () => {
  test('profile with a real company name', () => {
    const profile = { name: 'Acme Corporation' } as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(true);
  });

  test('profile with leading and trailing whitespace around name', () => {
    const profile = { name: '  Global Logistics Ltd  ' } as CompanyProfile;
    expect(isCompanyConfigured(profile)).toBe(true);
  });
});
