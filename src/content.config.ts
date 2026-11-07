import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

const experience = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/experience' }),
  schema: z.object({
    title: z.string(),
    company: z.string(),
    dates: z.string(),
    location: z.string().optional(),
    stack: z.array(z.string()).default([]),
    bullets: z.array(z.string()).default([]),
    featured: z.boolean().default(false),
    kind: z.enum(['role', 'education']).default('role'),
    order: z.number(),
  }),
});

const projects = defineCollection({
  loader: glob({ pattern: '**/*.md', base: './src/content/projects' }),
  schema: z.object({
    title: z.string(),
    summary: z.string(),
    problem: z.string(),
    stack: z.array(z.string()).default([]),
    links: z
      .array(
        z.object({
          label: z.string(),
          href: z.url(),
        }),
      )
      .default([]),
    featured: z.boolean().default(false),
    order: z.number(),
  }),
});

export const collections = { experience, projects };
