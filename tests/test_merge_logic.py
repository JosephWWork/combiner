import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'ParameterCombiner'))
import merge_logic as ml  # noqa: E402


def P(name, expr, unit='mm', value=None, comment=''):
    return ml.ParamInfo(name, expr, unit, value if value is not None else 0.0, comment)


class FindDuplicates(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(ml.find_duplicates(['Width', 'Width_1', 'Width_2']),
                         {'Width_1': 'Width', 'Width_2': 'Width'})

    def test_chain_goes_to_root(self):
        self.assertEqual(ml.find_duplicates(['Width', 'Width_1', 'Width_1_1']),
                         {'Width_1': 'Width', 'Width_1_1': 'Width'})

    def test_no_root_means_not_duplicate(self):
        self.assertEqual(ml.find_duplicates(['Bolt_1', 'Bolt_2']), {})

    def test_non_numeric_suffix_ignored(self):
        self.assertEqual(ml.find_duplicates(['Plate', 'Plate_A']), {})


class RewriteExpression(unittest.TestCase):
    m = {'Width_1': 'Width', 'Height_1': 'Height'}

    def test_whole_identifiers_only(self):
        self.assertEqual(ml.rewrite_expression('Width_1 * 2 + Width_10 + Height_1', self.m),
                         'Width * 2 + Width_10 + Height')

    def test_units_and_numbers_untouched(self):
        self.assertEqual(ml.rewrite_expression('10 mm + 1e3 * Width_1', self.m),
                         '10 mm + 1e3 * Width')

    def test_functions(self):
        self.assertEqual(ml.rewrite_expression('max(Width_1; Height_1)', self.m),
                         'max(Width; Height)')


class BuildPlan(unittest.TestCase):
    def test_matching_values_merge(self):
        plan = ml.build_plan([P('Width', '50 mm', value=5.0), P('Width_1', '50 mm', value=5.0)])
        self.assertEqual(plan.mapping, {'Width_1': 'Width'})
        self.assertEqual(plan.target_updates, {})

    def test_differing_value_uses_csv(self):
        std = {'Height': ml.Standard('Height', '25', 'mm')}
        plan = ml.build_plan([P('Height', '20 mm', value=2.0), P('Height_1', '25 mm', value=2.5)], std)
        self.assertEqual(plan.mapping, {'Height_1': 'Height'})
        self.assertEqual(plan.target_updates, {'Height': '25 mm'})

    def test_differing_value_not_in_csv_skipped(self):
        plan = ml.build_plan([P('Height', '20 mm', value=2.0), P('Height_1', '25 mm', value=2.5)], {})
        self.assertEqual(plan.mapping, {})
        self.assertEqual(len(plan.skipped), 1)

    def test_unit_difference_is_conflict(self):
        plan = ml.build_plan([P('T', '1 in', 'in', 2.54), P('T_1', '25.4 mm', 'mm', 2.54)])
        self.assertEqual(len(plan.skipped), 1)


class NormalizeExpression(unittest.TestCase):
    def test_bare_number_gets_unit(self):
        self.assertEqual(ml.normalize_expression('25,4', 'mm'), '25.4 mm')

    def test_expression_untouched(self):
        self.assertEqual(ml.normalize_expression('Width / 2', 'mm'), 'Width / 2')


class ParseStandards(unittest.TestCase):
    def test_comma(self):
        s = ml.parse_standards('﻿Name,Unit,Expression,Comment\nWidth,mm,50,w\n\n')
        self.assertEqual(s['Width'], ml.Standard('Width', '50', 'mm', 'w'))

    def test_semicolon_any_column_order(self):
        s = ml.parse_standards('expression;NAME;unit\n25,4;Height;mm\n')
        self.assertEqual(s['Height'].expression, '25,4')
        self.assertEqual(s['Height'].unit, 'mm')

    def test_missing_header(self):
        with self.assertRaises(ValueError):
            ml.parse_standards('Width,mm,50\n')


if __name__ == '__main__':
    unittest.main()
