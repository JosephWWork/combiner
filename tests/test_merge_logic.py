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
        self.assertEqual(plan.conflicts, [])

    def test_differing_value_is_conflict(self):
        plan = ml.build_plan([P('Height', '20 mm', value=2.0), P('Height_1', '25 mm', value=2.5)])
        self.assertEqual(plan.mapping, {})
        self.assertEqual(plan.conflicts, [ml.Conflict('Height_1', 'Height', '25 mm', '20 mm')])

    def test_unit_difference_is_conflict(self):
        plan = ml.build_plan([P('T', '1 in', 'in', 2.54), P('T_1', '25.4 mm', 'mm', 2.54)])
        self.assertEqual(len(plan.conflicts), 1)


class ModelParameterReview(unittest.TestCase):
    def test_model_duplicates_reported_not_merged(self):
        user = [P('Width', '50 mm', value=5.0)]
        model = [P('Depth', '30 mm', value=3.0), P('Depth_1', '30 mm', value=3.0),
                 P('Len', '10 mm', value=1.0), P('Len_1', '12 mm', value=1.2),
                 P('Width_1', '50 mm', value=5.0), P('d1', '5 mm', value=0.5)]
        plan = ml.build_plan(user, model)
        self.assertEqual(plan.mapping, {})
        self.assertEqual([(r.duplicate, r.target, r.same_value) for r in plan.review],
                         [('Depth_1', 'Depth', True), ('Len_1', 'Len', False), ('Width_1', 'Width', True)])
        self.assertEqual([r.duplicate for r in plan.review if r.duplicates_user_param], ['Width_1'])

    def test_user_pairs_not_in_review(self):
        user = [P('Width', '50 mm', value=5.0), P('Width_1', '50 mm', value=5.0)]
        plan = ml.build_plan(user, [P('d1', '5 mm', value=0.5)])
        self.assertEqual(plan.mapping, {'Width_1': 'Width'})
        self.assertEqual(plan.review, [])


if __name__ == '__main__':
    unittest.main()
