import type { Atlas, Concept } from './anatomy/anatomy';

export interface BodyRegion {
  id: string;
  name: string;
  subtitle: string;
  conceptNames: string[];
}

export const REGIONS: BodyRegion[] = [
  {
    id: 'head-neck',
    name: 'Head & neck',
    subtitle: 'Brain, senses & cervical spine',
    conceptNames: [
      'brain', 'cerebellum', 'skull', 'mandible', 'hyoid bone',
      'right eye', 'left eye', 'cervical vertebral column',
    ],
  },
  {
    id: 'chest',
    name: 'Chest',
    subtitle: 'Heart, lungs & rib cage',
    conceptNames: [
      'heart', 'right lung', 'left lung', 'trachea', 'sternum',
      'rib cage', 'diaphragm', 'esophagus', 'aorta', 'thoracic vertebral column',
    ],
  },
  {
    id: 'abdomen-pelvis',
    name: 'Abdomen & pelvis',
    subtitle: 'Digestion, kidneys & pelvic organs',
    conceptNames: [
      'liver', 'stomach', 'pancreas', 'spleen', 'right kidney',
      'left kidney', 'small intestine', 'large intestine', 'urinary bladder', 'pelvis',
    ],
  },
  {
    id: 'arms-hands',
    name: 'Arms & hands',
    subtitle: 'Shoulders, arms & hands',
    conceptNames: [
      'right clavicle', 'left clavicle', 'right scapula', 'left scapula',
      'right humerus', 'left humerus', 'right radius', 'left radius',
      'right ulna', 'left ulna', 'right hand', 'left hand',
    ],
  },
  {
    id: 'legs-feet',
    name: 'Legs & feet',
    subtitle: 'Thighs, knees, lower legs & feet',
    conceptNames: [
      'right femur', 'left femur', 'right patella', 'left patella',
      'right tibia', 'left tibia', 'right fibula', 'left fibula',
      'right foot', 'left foot',
    ],
  },
];

export function getRegionConcepts(atlas: Atlas, regionId: string): Concept[] {
  const region = REGIONS.find((entry) => entry.id === regionId);
  if (!region) return [];

  const conceptsByName = new Map(atlas.concepts.map((concept) => [concept.name.toLowerCase(), concept]));
  return region.conceptNames
    .map((name) => conceptsByName.get(name.toLowerCase()))
    .filter((concept): concept is Concept => concept !== undefined);
}

export const FEATURED: { name: string; label: string; description: string }[] = [
  { name: 'heart', label: 'Heart', description: 'Explore the chambers at the center of circulation.' },
  { name: 'brain', label: 'Brain', description: 'Discover the body’s center for sensation and movement.' },
  { name: 'vertebral column', label: 'Spine', description: 'Follow the vertebrae supporting the head and trunk.' },
  { name: 'right femur', label: 'Femur', description: 'Inspect the thigh bone connecting the hip and knee.' },
];
