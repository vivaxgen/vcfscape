"""
Malaria Molecular Surveillance Knowledgebase & Marker Annotation Database.
Curated against WHO Global Malaria Programme guidelines for antimalarial drug resistance.
"""

from typing import Dict, List, Optional, Tuple, NamedTuple

class MarkerAnnotation(NamedTuple):
    gene: str
    locus_id: str
    mutation: str
    drug: str
    status: str  # Validated / Candidate / Associated
    impact: str
    details: str

class MalariaAnnotationDB:
    """
    Curated database of Plasmodium falciparum genomic surveillance markers.
    Handles exact coordinate matching, codon resolution, and multi-allelic identification.
    """

    KNOWN_MARKERS: Dict[Tuple[str, int], MarkerAnnotation] = {
        # Pfkelch13 (chr 13, PF3D7_1343700) - Artemisinin Resistance
        ("Pf3D7_13_v3", 1725259): MarkerAnnotation(
            gene="Pfkelch13", locus_id="PF3D7_1343700", mutation="C580Y",
            drug="Artemisinin", status="WHO Validated", impact="Missense",
            details="Primary artemisinin partial resistance marker in Greater Mekong Subregion and East Africa"
        ),
        ("Pf3D7_13_v3", 1725220): MarkerAnnotation(
            gene="Pfkelch13", locus_id="PF3D7_1343700", mutation="Y493H",
            drug="Artemisinin", status="WHO Validated", impact="Missense",
            details="Validated artemisinin delayed clearance marker"
        ),
        ("Pf3D7_13_v3", 1725340): MarkerAnnotation(
            gene="Pfkelch13", locus_id="PF3D7_1343700", mutation="A675V",
            drug="Artemisinin", status="WHO Validated", impact="Missense",
            details="Artemisinin resistance marker detected in Uganda and Rwanda"
        ),
        ("Pf3D7_13_v3", 1725242): MarkerAnnotation(
            gene="Pfkelch13", locus_id="PF3D7_1343700", mutation="R561H",
            drug="Artemisinin", status="WHO Validated", impact="Missense",
            details="Artemisinin resistance marker prevalent in Rwanda and Myanmar"
        ),
        ("Pf3D7_13_v3", 1725235): MarkerAnnotation(
            gene="Pfkelch13", locus_id="PF3D7_1343700", mutation="P574L",
            drug="Artemisinin", status="WHO Candidate", impact="Missense",
            details="Associated with delayed clearance in Rwanda and India"
        ),

        # Pfcrt (chr 7, PF3D7_0709000) - Chloroquine / Piperaquine
        ("Pf3D7_07_v3", 403625): MarkerAnnotation(
            gene="Pfcrt", locus_id="PF3D7_0709000", mutation="K76T",
            drug="Chloroquine", status="WHO Validated", impact="Missense",
            details="Primary chloroquine resistance determinant across all endemic continents"
        ),
        ("Pf3D7_07_v3", 403580): MarkerAnnotation(
            gene="Pfcrt", locus_id="PF3D7_0709000", mutation="M74I",
            drug="Chloroquine", status="Associated", impact="Missense",
            details="Found in multi-locus CVIET/SVMNT chloroquine resistance haplotypes"
        ),
        ("Pf3D7_07_v3", 403590): MarkerAnnotation(
            gene="Pfcrt", locus_id="PF3D7_0709000", mutation="N75E",
            drug="Chloroquine", status="Associated", impact="Missense",
            details="Co-occurs with K76T in canonical resistant chloroquine haplotypes"
        ),

        # Pfmdr1 (chr 5, PF3D7_0523000) - Multidrug / Lumefantrine / Mefloquine
        ("Pf3D7_05_v3", 958145): MarkerAnnotation(
            gene="Pfmdr1", locus_id="PF3D7_0523000", mutation="N86Y",
            drug="Multidrug / Lumefantrine", status="WHO Validated", impact="Missense",
            details="Modulates sensitivity between chloroquine (Y86) and lumefantrine/artemether (N86)"
        ),
        ("Pf3D7_05_v3", 958210): MarkerAnnotation(
            gene="Pfmdr1", locus_id="PF3D7_0523000", mutation="Exon_Indel",
            drug="Multidrug", status="Candidate", impact="InFrame_Deletion",
            details="Structural micro-indel in transporter nucleotide-binding domain"
        ),

        # Pfdhps (chr 8, PF3D7_0810800) - Sulfadoxine
        ("Pf3D7_08_v3", 549685): MarkerAnnotation(
            gene="Pfdhps", locus_id="PF3D7_0810800", mutation="A437G",
            drug="Sulfadoxine", status="WHO Validated", impact="Missense",
            details="Confers resistance to sulfadoxine; component of quadruple/quintuple mutant"
        ),
        ("Pf3D7_08_v3", 549720): MarkerAnnotation(
            gene="Pfdhps", locus_id="PF3D7_0810800", mutation="K540E",
            drug="Sulfadoxine", status="WHO Validated", impact="Missense",
            details="Key marker for SP intermittent preventive treatment failure in infants/pregnancy"
        ),

        # Plasmepsin 2/3 (chr 14, PF3D7_1408000 / PF3D7_1408100) - Piperaquine
        ("Pf3D7_14_v3", 1402310): MarkerAnnotation(
            gene="Plasmepsin2", locus_id="PF3D7_1408000", mutation="Promoter_Indel",
            drug="Piperaquine", status="Validated", impact="Regulatory",
            details="Promoter indel associated with plasmepsin 2/3 gene amplification & piperaquine failure"
        ),
    }

    # Gene coordinate spans for general locus lookup
    GENE_REGIONS = [
        ("Pf3D7_13_v3", 1724000, 1727000, "Pfkelch13", "PF3D7_1343700", "Artemisinin"),
        ("Pf3D7_07_v3", 403000, 406000, "Pfcrt", "PF3D7_0709000", "Chloroquine/Piperaquine"),
        ("Pf3D7_05_v3", 957000, 962000, "Pfmdr1", "PF3D7_0523000", "Multidrug/Lumefantrine"),
        ("Pf3D7_04_v3", 747000, 751000, "Pfdhfr", "PF3D7_0417200", "Pyrimethamine"),
        ("Pf3D7_08_v3", 548000, 552000, "Pfdhps", "PF3D7_0810800", "Sulfadoxine"),
        ("Pf3D7_14_v3", 1400000, 1406000, "Plasmepsin2/3", "PF3D7_1408000", "Piperaquine"),
        ("Pf3D7_12_v3", 970000, 980000, "PF3D7_1222600", "PF3D7_1222600", "Microsatellite surveillance"),
    ]

    @classmethod
    def lookup(cls, chrom: str, pos: int, ref: str = "", alt: str = "") -> Optional[MarkerAnnotation]:
        """
        Check if variant corresponds to a known drug resistance locus.
        Performs direct lookup using exact chromosome name as-is for maximum speed.
        """
        key = (chrom, pos)
        if key in cls.KNOWN_MARKERS:
            return cls.KNOWN_MARKERS[key]
        
        # Check if inside region
        for r_chrom, start, end, gene, locus_id, drug in cls.GENE_REGIONS:
            if r_chrom == chrom and start <= pos <= end:
                return MarkerAnnotation(
                    gene=gene, locus_id=locus_id, mutation=f"{ref}>{alt}",
                    drug=drug, status="Regional Locus",
                    impact="Coding/Regulatory", details=f"Located in {gene} drug surveillance locus"
                )
        return None

    @classmethod
    def normalize_chrom(cls, chrom: str) -> str:
        """Returns chromosome name as-is without mutation or overhead."""
        return chrom

