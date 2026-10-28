"""Catálogo fictício de categorias e itens para a base sintética."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategorySpec:
    category_id: str
    name: str
    engineering: bool
    kind: str  # material | service | works (define prazos e aditivos)
    price_scale: float  # preço unitário mediano típico (R$)
    qty_scale: float  # quantidade típica por item
    supplier_word: str  # usado para compor razões sociais fictícias
    items: tuple[tuple[str, str], ...]  # (descrição, unidade)


CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(
        "MAT-ESC",
        "Material de escritório",
        False,
        "material",
        25,
        200,
        "Papelaria",
        (
            ("Papel A4 75g, resma 500 folhas", "resma"),
            ("Caneta esferográfica azul", "unidade"),
            ("Toner para impressora laser", "unidade"),
            ("Pasta suspensa", "unidade"),
            ("Grampeador de mesa", "unidade"),
            ("Envelope pardo A4", "pacote"),
            ("Bloco de notas adesivas", "pacote"),
            ("Etiqueta adesiva A4", "caixa"),
        ),
    ),
    CategorySpec(
        "MED",
        "Medicamentos",
        False,
        "material",
        8,
        2000,
        "Farma",
        (
            ("Dipirona sódica 500mg", "comprimido"),
            ("Amoxicilina 500mg", "cápsula"),
            ("Soro fisiológico 0,9% 500ml", "frasco"),
            ("Insulina NPH 100UI/ml", "frasco"),
            ("Omeprazol 20mg", "cápsula"),
            ("Losartana potássica 50mg", "comprimido"),
            ("Paracetamol 750mg", "comprimido"),
            ("Ibuprofeno 600mg", "comprimido"),
        ),
    ),
    CategorySpec(
        "ALIM",
        "Gêneros alimentícios",
        False,
        "material",
        12,
        1500,
        "Alimentos",
        (
            ("Arroz tipo 1, pacote 5kg", "pacote"),
            ("Feijão carioca tipo 1, 1kg", "kg"),
            ("Carne bovina patinho", "kg"),
            ("Leite UHT integral 1L", "litro"),
            ("Óleo de soja 900ml", "unidade"),
            ("Café torrado e moído 500g", "pacote"),
            ("Frango congelado", "kg"),
            ("Banana prata", "kg"),
        ),
    ),
    CategorySpec(
        "COMB",
        "Combustíveis",
        False,
        "material",
        6,
        8000,
        "Combustíveis",
        (
            ("Gasolina comum", "litro"),
            ("Óleo diesel S10", "litro"),
            ("Etanol hidratado", "litro"),
            ("Arla 32", "litro"),
        ),
    ),
    CategorySpec(
        "LIMP",
        "Serviços de limpeza e conservação",
        False,
        "service",
        4500,
        12,
        "Serviços",
        (
            ("Posto de limpeza 44h semanais", "posto/mês"),
            ("Limpeza de vidros", "m²"),
            ("Posto de copeiragem", "posto/mês"),
            ("Jardinagem e roçada", "m²"),
        ),
    ),
    CategorySpec(
        "MANUT",
        "Manutenção predial",
        True,
        "service",
        60,
        600,
        "Engenharia",
        (
            ("Reparo de cobertura", "m²"),
            ("Pintura acrílica de paredes", "m²"),
            ("Manutenção elétrica predial", "hora"),
            ("Manutenção hidráulica", "hora"),
            ("Impermeabilização de laje", "m²"),
        ),
    ),
    CategorySpec(
        "TI",
        "Equipamentos de TI",
        False,
        "material",
        3500,
        20,
        "Tecnologia",
        (
            ("Notebook 16GB RAM SSD 512GB", "unidade"),
            ("Monitor LED 24 polegadas", "unidade"),
            ("Computador desktop", "unidade"),
            ("Switch 24 portas gerenciável", "unidade"),
            ("Nobreak 1500VA", "unidade"),
            ("Impressora multifuncional", "unidade"),
        ),
    ),
    CategorySpec(
        "HOSP",
        "Material hospitalar",
        False,
        "material",
        2,
        10000,
        "Hospitalar",
        (
            ("Luva de procedimento", "unidade"),
            ("Seringa descartável 5ml", "unidade"),
            ("Máscara cirúrgica tripla", "unidade"),
            ("Compressa de gaze", "pacote"),
            ("Cateter intravenoso", "unidade"),
            ("Esparadrapo 10cm x 4,5m", "rolo"),
        ),
    ),
    CategorySpec(
        "OBRAS",
        "Obras e serviços de engenharia",
        True,
        "works",
        250,
        800,
        "Construtora",
        (
            ("Pavimentação asfáltica CBUQ", "m²"),
            ("Construção de edificação em alvenaria", "m²"),
            ("Drenagem pluvial com tubo de concreto", "m"),
            ("Calçamento com bloquete", "m²"),
            ("Reforma de unidade de saúde", "m²"),
        ),
    ),
    CategorySpec(
        "VEIC",
        "Locação de veículos",
        False,
        "service",
        4000,
        12,
        "Locadora",
        (
            ("Locação de veículo sedan com motorista", "mês"),
            ("Locação de caminhonete 4x4", "mês"),
            ("Locação de van 15 lugares", "mês"),
            ("Locação de ambulância simples remoção", "mês"),
        ),
    ),
    CategorySpec(
        "CONS",
        "Consultoria e treinamento",
        False,
        "service",
        300,
        100,
        "Consultoria",
        (
            ("Hora técnica de consultoria", "hora"),
            ("Curso de capacitação", "turma"),
            ("Elaboração de projeto técnico", "hora"),
            ("Assessoria contábil", "hora"),
        ),
    ),
    CategorySpec(
        "MOB",
        "Mobiliário",
        False,
        "material",
        700,
        40,
        "Móveis",
        (
            ("Cadeira giratória com braços", "unidade"),
            ("Mesa de escritório 1,20m", "unidade"),
            ("Armário de aço 2 portas", "unidade"),
            ("Estante de aço", "unidade"),
            ("Arquivo de aço 4 gavetas", "unidade"),
        ),
    ),
)

# Municípios fictícios (não correspondem a municípios reais do ES).
CITIES = (
    "Serra Dourada do Leste",
    "Águas do Horizonte",
    "Porto das Garças",
    "Vila Esperança do Sul",
    "Campo Belo da Serra",
    "Rio Sereno",
    "Lagoa Azul do Norte",
    "Monte Verde Capixaba",
    "São Jerônimo das Pedras",
    "Nova Aurora do Leste",
    "Ribeirão das Brisas",
    "Alto Sereno",
    "Barra do Sol",
)

STATE_AREAS = (
    "Saúde",
    "Educação",
    "Segurança Pública",
    "Infraestrutura",
    "Agricultura",
    "Fazenda",
    "Justiça",
    "Meio Ambiente",
    "Cultura",
    "Turismo",
)

FEDERAL_AGENCIES = (
    "Instituto Federal Fictício — Campus Serra Dourada",
    "Universidade Federal Fictícia — Campus Rio Sereno",
    "Superintendência Regional Fictícia de Obras",
    "Hospital Universitário Fictício",
)

SANCTION_TYPES = (
    "Impedimento/proibição de contratar com prazo determinado",
    "Declaração de Inidoneidade com prazo determinado",
    "Suspensão - Lei de Licitações",
    "Multa - Lei Anticorrupção",
)

SANCTION_AUTHORITIES = (
    "Controladoria Fictícia do Estado",
    "Tribunal de Contas Fictício do Estado",
    "Controladoria-Geral Fictícia",
    "Procuradoria Fictícia do Município",
)
